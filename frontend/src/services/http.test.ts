import { afterEach, expect, it, vi } from 'vitest'
import { createHttpServices, login, logout, mapReport, request } from './http'
import { File as BufferFile } from 'node:buffer'
import { readMemoFile, MAX_MEMO_BYTES } from './upload'
const file = (text: string | Uint8Array, name = '메모.txt', type = 'text/plain') =>
  new BufferFile([text], name, { type }) as unknown as File
const now = '2026-10-21T00:00:00Z'
const memo = {
  id: 'memo-id',
  company_name: null,
  title: '메모',
  current_version: 3,
  created_at: now,
  updated_at: now,
}
const task = {
  task_id: 'task-id',
  memo_id: memo.id,
  base_memo_version: 1,
  disclosure_receipt_no: '20261020000245',
  company_name_snapshot: '기업',
  status: 'QUEUED',
  current_stage: 'REQUEST_VALIDATION',
  created_at: now,
  updated_at: now,
  has_warnings: false,
  error_stage: null,
  error_code: null,
  started_at: null,
  completed_at: null,
}
function respond(path: string, init?: RequestInit) {
  const data =
    path === '/api/v1/auth/login'
      ? { access_token: 'server-token' }
      : path === '/api/v1/users/me'
        ? { id: 'user-id', email: 'user@example.test', role: 'RA', organization_id: 'org-id' }
        : path.startsWith('/api/v1/filings?')
          ? [
              {
                id: 'filing-id',
                company_name: '기업',
                receipt_no: task.disclosure_receipt_no,
                filing_type: '정정',
                is_correction: true,
                filed_at: now,
              },
            ]
          : path.includes('/filings/filing-id/versions?')
            ? [{ version: 1, created_at: now }]
            : path.includes('/filings/filing-id/versions/1')
              ? { version: 1, raw_content: '공시 본문', created_at: now }
              : path.includes('/memos/memo-id/versions?')
                ? [{ version: 1 }, { version: 3 }]
                : path.includes('/memos/memo-id/versions/')
                  ? {
                      version: Number(path.split('/').at(-1)),
                      content: '메모 본문',
                      created_at: now,
                    }
                  : path === '/api/v1/memos' && init?.method === 'POST'
                    ? memo
                    : path.startsWith('/api/v1/memos?')
                      ? [memo]
                      : path === '/api/v1/analyses' && init?.method === 'POST'
                        ? { task_id: task.task_id }
                        : path === '/api/v1/analyses/task-id'
                          ? task
                          : path.endsWith('/perspectives')
                            ? [
                                {
                                  perspective_type: 'FX_HEDGE',
                                  selection_reason: '환위험',
                                  question: '확인',
                                  status: 'RUNNING',
                                  result_json: null,
                                  failure_code: null,
                                },
                              ]
                            : path.endsWith('/report')
                              ? null
                              : path.startsWith('/api/v1/analyses?')
                                ? [task]
                                : undefined
  if (data === undefined) throw new Error(`Unexpected request ${path}`)
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }))
}
afterEach(() => {
  logout()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
it('로그인 토큰을 헤더로 보내고 선택한 과거 버전과 실제 접수번호로 분석을 접수합니다', async () => {
  const fetcher = vi.fn(respond)
  vi.stubGlobal('fetch', fetcher)
  await login('user@example.test', 'password')
  const service = createHttpServices()
  const result = await service.analyses.start({
    filingId: 'filing-id',
    memoId: memo.id,
    memoVersion: 1,
  })
  expect(result.baseMemoVersion).toBe(1)
  expect(result.perspectives[0]?.type).toBe('FX_HEDGE')
  const call = fetcher.mock.calls.find(([url]) => url === '/api/v1/analyses')!
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    memo_id: memo.id,
    memo_version: 1,
    disclosure_receipt_no: '20261020000245',
  })
  expect((call[1]!.headers as Headers).get('Authorization')).toBe('Bearer server-token')
})
it('파일을 multipart로 전송하고 서버의 기업 미확정 상태와 본문을 보존합니다', async () => {
  const fetcher = vi.fn(respond)
  vi.stubGlobal('fetch', fetcher)
  const value = await createHttpServices().memos.upload(file('새 본문'), '새 제목', '기업')
  expect(value.companyName).toBeNull()
  expect(value.versions[0]?.content).toBe('메모 본문')
  const [, options] = fetcher.mock.calls.find(([url]) => url === '/api/v1/memos')!
  expect(options?.body).toBeInstanceOf(FormData)
  expect((options!.headers as Headers).has('Content-Type')).toBe(false)
  expect((options!.body as FormData).get('title')).toBe('새 제목')
  expect((options!.body as FormData).get('company_id')).toBe('기업')
})
it('서버 오류를 전파하고 만료된 인증을 해제합니다', async () => {
  vi.stubGlobal('fetch', vi.fn(respond))
  await login('user@example.test', 'password')
  const expired = vi.fn()
  window.addEventListener('session-expired', expired)
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { message: 'TOKEN_EXPIRED' } }), { status: 401 }),
      ),
    ),
  )
  await expect(request('/memos')).rejects.toThrow('TOKEN_EXPIRED')
  expect(expired).toHaveBeenCalledOnce()
  window.removeEventListener('session-expired', expired)
})
it('보고서 원문과 제안 및 인용을 보존하고 실행 가능한 URL을 차단합니다', () => {
  const source = { document_id: 'doc', location: '1쪽', quote: '원문', url: 'javascript:alert(1)' }
  const result = mapReport({
    id: 'report',
    analysis_task_id: 'task',
    content: '저장된 본문',
    generated_at: now,
    saved_at: now,
    no_additional_analysis_reason: null,
    report_json: {
      base: {
        proposals: [
          {
            claim_id: '1',
            impact_type: 'FACT_UPDATE',
            before_text: '기존',
            after_text: '수정',
            reason: '사유',
            evidence: [source],
          },
        ],
      },
      sources: [source],
      corrections: [{ label: '금액', before: '1', after: '2' }],
    },
  })
  expect(result.content).toBe('저장된 본문')
  expect(result.findings[0]?.evidenceIds).toEqual(['source-0'])
  expect(result.evidence[0]?.url).toBeNull()
  expect(result.summary).toBe('')
})
it('업로드 본문의 공백을 보존하고 잘못된 입력을 거부합니다', async () => {
  expect(await readMemoFile(file('\uFEFF 첫 문단\n\n둘째 문단 '))).toBe(' 첫 문단\n\n둘째 문단 ')
  for (const value of [
    file('내용', 'a.pdf'),
    file('내용', 'a.txt', 'text/html'),
    file(' \n'),
    file('내용\0'),
    file(new Uint8Array([255])),
    file('x'.repeat(MAX_MEMO_BYTES + 1)),
  ])
    await expect(readMemoFile(value)).rejects.toThrow()
})

it('비밀번호 변경의 204 응답을 처리하고 토큰을 폐기합니다', async () => {
  const { changePassword, hasSession, signup } = await import('./http')
  const fetcher = vi.fn(respond)
  vi.stubGlobal('fetch', fetcher)
  await login('user@example.test', 'password')
  fetcher.mockImplementation((path, options) => {
    if (path.endsWith('/password')) return Promise.resolve(new Response(null, { status: 204 }))
    if (path.endsWith('/signup'))
      return Promise.resolve(new Response(JSON.stringify({ id: 'new-user' }), { status: 201 }))
    return respond(path, options)
  })
  await signup('new@example.com', 'password-test-123', '새 조직', '박건민')
  await changePassword('password', 'new-password-123')
  expect(hasSession()).toBe(false)
  const call = fetcher.mock.calls.find(([url]) => url.endsWith('/password'))!
  expect(call[1]?.method).toBe('PATCH')
  expect(JSON.parse(call[1]?.body as string)).toEqual({
    current_password: 'password',
    new_password: 'new-password-123',
  })
})

it('로그인 거부 시 회원가입 안내를 표시합니다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: { code: 'INVALID_CREDENTIALS', message: 'Invalid credentials' },
          }),
          { status: 401 },
        ),
      ),
    ),
  )
  await expect(login('unknown@example.com', 'password')).rejects.toThrow('처음 이용하시면 회원가입')
})

it('신규공시도 선택한 메모 버전으로 분석을 접수합니다', async () => {
  const fetcher = vi.fn((path: string, init?: RequestInit) => {
    if (path.startsWith('/api/v1/filings?'))
      return Promise.resolve(
        new Response(
          JSON.stringify([
            {
              id: 'filing-id',
              company_name: '기업',
              receipt_no: task.disclosure_receipt_no,
              filing_type: '신규공시',
              is_correction: false,
              filed_at: now,
            },
          ]),
          { status: 200 },
        ),
      )
    return respond(path, init)
  })
  vi.stubGlobal('fetch', fetcher)
  const result = await createHttpServices().analyses.start({ filingId: 'filing-id', memoId: memo.id, memoVersion: 1 })
  expect(result.id).toBe(task.task_id)
  const sent = fetcher.mock.calls.find(([path]) => path === '/api/v1/analyses')!
  expect(JSON.parse(sent[1]!.body as string)).toEqual({ memo_id: memo.id, memo_version: 1, disclosure_receipt_no: task.disclosure_receipt_no })
})


it('빈 제안의 유지 판단과 연결 근거를 보존합니다', () => {
  const source = { document_id: 'filing:ir', location: 'line:1', quote: '실적 발표 일정 안내' }
  const row = { id: 'r', analysis_task_id: task.task_id, content: '보고서', generated_at: now,
    saved_at: now, no_additional_analysis_reason: null,
    report_json: { base: { proposals: [] }, memo_review: { status: 'KEEP' as const,
      reason: '일정 안내이며 기존 수치 변경이 없어 유지합니다.', evidence: [source] } } }
  const report = mapReport(row)
  expect(report.findings).toEqual([])
  expect(report.memoReview?.status).toBe('KEEP')
  expect(report.memoReview?.reason).toContain('유지합니다')
  expect(report.memoReview?.evidenceIds).toEqual(['source-0'])
  expect(report.evidence[0]?.quote).toBe(source.quote)
  expect(mapReport({ ...row, report_json: { base: { proposals: [] } } }).memoReview?.status).toBe('HOLD')
})

it('보고서에 저장된 관점 선택과 미선택 이유를 함께 읽습니다', () => {
  const report = mapReport({ id: 'r', analysis_task_id: task.task_id, content: '보고서', generated_at: now,
    saved_at: now, no_additional_analysis_reason: null, report_json: { base: {
      selected: [{ perspective_type: 'FINANCE', selection_reason: '현금흐름 확인' }],
      not_selected: [{ perspective_type: 'INDUSTRY_CONTRACT', reason: '계약 영향 없음' },
                     { perspective_type: 'FX_HEDGE', reason: '환율 영향 없음' }],
    } } })
  expect(report.perspectiveDecisions).toHaveLength(3)
  expect(report.perspectiveDecisions?.find((p) => p.type === 'FINANCE')).toEqual({
    type: 'FINANCE', selected: true, reason: '현금흐름 확인',
  })
  expect(report.perspectiveDecisions?.filter((p) => !p.selected).map((p) => p.reason)).toEqual(['계약 영향 없음', '환율 영향 없음'])
})

it('수정 문장 없이 재검토 관점과 메모·공시 양쪽의 근거를 읽습니다', () => {
  const memoSource = { document_id: 'memo:1', location: 'line:1', quote: '기존 로열티 성장 가정' }
  const filingSource = { document_id: 'filing:new', location: 'line:2', quote: '적용 제품 범위 확대' }
  const report = mapReport({ id: 'r', analysis_task_id: task.task_id, content: '보고서', generated_at: now,
    saved_at: now, no_additional_analysis_reason: null, report_json: {
      sources: [memoSource], base: { proposals: [], review_points: [{
        perspective_type: 'FINANCE', title: '로열티 성장 가정 재검토', memo_view: '기존 가정입니다.',
        disclosure_fact: '적용 제품 범위가 확대됐습니다.', reason: '기존 반영 범위를 확인합니다.',
        question: '기존 전망에 반영되어 있습니까?', check_items: ['제품별 계약 조건을 확인합니다.'],
        evidence: [memoSource, filingSource],
      }] },
    } })
  expect(report.findings).toEqual([])
  expect(report.memoReview).toBeUndefined()
  expect(report.evidence).toHaveLength(2)
  expect(report.reviewPoints?.[0]).toMatchObject({
    title: '로열티 성장 가정 재검토', question: '기존 전망에 반영되어 있습니까?',
    evidenceIds: ['source-0', 'source-1'],
  })
})
