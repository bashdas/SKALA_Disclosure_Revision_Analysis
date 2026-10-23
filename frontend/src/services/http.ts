import { notifyError } from '../lib/notifications'
import { disclosureUrl } from '../lib/format'
import { ref } from 'vue'
import type { Services } from './contracts'
import { readKey } from './contracts'
import { readMemoFile } from './upload'
import type {
  AnalysisTask,
  Company,
  Filing,
  Memo,
  Perspective,
  ReviewReport,
  Evidence,
  Finding,
} from '../types/domain'

export interface CurrentUser {
  id: string
  email: string
  name?: string
  role: string
}
export const currentUser = ref<CurrentUser | null>(null)
const TOKEN_KEY = 'disclosure-check.token'
let token = ''
try {
  token = sessionStorage.getItem(TOKEN_KEY) ?? ''
} catch {
  /* 저장소가 차단되면 현재 세션에서만 인증합니다. */
}
export const hasSession = () => !!token
export function logout() {
  token = ''
  currentUser.value = null
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 메모리 토큰도 함께 지웁니다. */
  }
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public existingTaskId?: string,
  ) {
    super(message)
  }
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
  format: 'json' | 'blob' = 'json',
): Promise<T> {
  const headers = new Headers(options.headers)
  if (authenticated && token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      signal: options.signal ?? AbortSignal.timeout(65000),
    })
  } catch {
    const error = new Error('서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.')
    if (!options.signal?.aborted) notifyError(error)
    throw error
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    if (response.status === 401 && authenticated) {
      const hadToken = !!token
      logout()
      if (hadToken) window.dispatchEvent(new Event('session-expired'))
    }
    const error = new ApiError(
      response.status,
      (body.error?.code === 'INVALID_CREDENTIALS'
        ? '이메일 또는 비밀번호를 확인해 주세요. 처음 이용하시면 회원가입을 진행해 주세요.'
        : body.error?.message) ??
        (response.status === 502 || response.status === 503
          ? '백엔드 서버에 연결하지 못했습니다. 서버 실행 상태를 확인해 주세요.'
          : typeof body.detail === 'string'
            ? body.detail
            : `요청에 실패했습니다 (${response.status}).`),
      body.error?.existing_task_id,
    )
    if (response.status !== 409) notifyError(error)
    throw error
  }
  if (response.status === 204) return undefined as T
  return (format === 'blob' ? response.blob() : response.json()) as Promise<T>
}
export async function login(email: string, password: string) {
  const result = await request<{ access_token: string }>(
    '/auth/login',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    },
    false,
  )
  token = result.access_token
  try {
    currentUser.value = await request<CurrentUser>('/users/me')
    try {
      sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* 현재 탭의 인증을 유지합니다. */
    }
  } catch (error) {
    logout()
    throw error
  }
}
export async function restoreSession() {
  if (token) currentUser.value = await request<CurrentUser>('/users/me')
}
interface FilingRow {
  corp_code?: string | null
  title?: string | null
  is_correction?: boolean
  origin_receipt_no?: string | null
  id: string
  company_name: string
  receipt_no: string
  filing_type: string
  filed_at: string
}
interface MemoRow {
  id: string
  company_name: string | null
  title: string
  current_version: number
  created_at: string
  updated_at: string
}
interface TaskRow {
  task_id: string
  memo_id: string
  base_memo_version: number
  disclosure_receipt_no: string
  company_name_snapshot: string | null
  status: AnalysisTask['status']
  current_stage: AnalysisTask['currentStage']
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
  has_warnings: boolean
  error_stage: AnalysisTask['errorStage']
  error_code: string | null
}
interface VersionRow {
  version: number
  created_at: string
  content?: string
  raw_content?: string
  original_filename?: string
  size_bytes?: number
  content_hash?: string
}
interface Source {
  document_id: string
  location: string
  quote: string
  published_at?: string
  url?: string
}
interface Proposal {
  claim_id: string
  impact_type: Finding['impactType']
  before_text: string
  after_text: string | null
  reason: string
  evidence: Source[]
}
interface ReportRow {
  id: string
  analysis_task_id: string
  content: string
  generated_at: string
  saved_at: string | null
  no_additional_analysis_reason: string | null
  report_json: {
    sources?: Source[]
    memo_review?: { status: 'KEEP' | 'HOLD'; reason: string; evidence: Source[] } | null
    base?: { summary?: string; proposals?: Proposal[];
      review_points?: { perspective_type: Perspective['type']; title: string;
        view_type?: 'MEMO_REVIEW' | 'DISCLOSURE_REVIEW'; condition?: string | null;
        memo_view: string | null; disclosure_fact: string; reason: string; question: string;
        check_items: string[]; evidence: Source[] }[];
      selected?: { perspective_type: Perspective['type']; selection_reason: string }[];
      not_selected?: { perspective_type: Perspective['type']; reason: string }[] }
    summary_claims?: { text: string }[]
    corrections?: ReviewReport['changes']
    warnings?: string[]
  }
}
export function mapReport(row: ReportRow): ReviewReport {
  const data = row.report_json,
    proposals = data.base?.proposals ?? [],
    reviewPoints = data.base?.review_points ?? []
  const sources = [...(data.sources ?? [])]
  for (const source of [...proposals.flatMap((p) => p.evidence), ...reviewPoints.flatMap((p) => p.evidence), ...(data.memo_review?.evidence ?? [])]) {
      if (
        !sources.some(
          (s) =>
            s.document_id === source.document_id &&
            s.location === source.location &&
            s.quote === source.quote,
        )
      )
        sources.push(source)
    }
  const evidence: Evidence[] = sources.map((s, i) => ({
    id: `source-${i}`,
    title: s.document_id,
    kind: 'external',
    publishedAt: s.published_at ?? '',
    quote: s.quote,
    context: s.quote,
    url: safeUrl(s.url),
    documentId: s.document_id,
    version: null,
    paragraph: null,
    location: s.location,
  }))
  return {
    id: row.id,
    taskId: row.analysis_task_id,
    version: 1,
    title: '공시 영향 분석 보고서',
    generatedAt: row.generated_at,
    savedAt: row.saved_at,
    content: row.content,
    summary: data.summary_claims?.map((c) => c.text).join('\n') || data.base?.summary || '',
    changes: data.corrections ?? [],
    warnings: data.warnings ?? [],
    noAdditionalAnalysisReason: row.no_additional_analysis_reason,
    evidence,
    perspectiveDecisions: data.base?.selected || data.base?.not_selected ? [
      ...(data.base.selected ?? []).map((p) => ({ type: p.perspective_type, selected: true, reason: p.selection_reason })),
      ...(data.base.not_selected ?? []).map((p) => ({ type: p.perspective_type, selected: false, reason: p.reason })),
    ] : undefined,
    memoReview: proposals.length || reviewPoints.length ? undefined : {
      status: data.memo_review?.status ?? 'HOLD',
      reason: data.memo_review?.reason || '이 보고서에는 유지 또는 수정 여부를 확인할 판단 근거가 저장되지 않았습니다. 재분석이 필요합니다.',
      evidenceIds: (data.memo_review?.evidence ?? []).map((s) =>
        `source-${sources.findIndex((e) => e.document_id === s.document_id && e.location === s.location && e.quote === s.quote)}`,
      ),
    },
    reviewPoints: reviewPoints.map((p) => ({
      viewType: p.view_type ?? 'MEMO_REVIEW',
      perspectiveType: p.perspective_type,
      title: p.title,
      memoView: p.memo_view,
      condition: p.condition ?? null,
      disclosureFact: p.disclosure_fact,
      reason: p.reason,
      question: p.question,
      checkItems: p.check_items,
      evidenceIds: p.evidence.map((s) =>
        `source-${sources.findIndex((e) => e.document_id === s.document_id && e.location === s.location && e.quote === s.quote)}`,
      ),
    })),
    findings: proposals.map((p) => ({
      id: p.claim_id,
      beforeText: p.before_text,
      newFact: p.evidence.map((e) => e.quote).join('\n'),
      impactType: p.impact_type,
      reason: p.reason,
      suggestion: p.after_text ?? '',
      memoParagraph: null,
      evidenceIds: p.evidence.map(
        (s) =>
          `source-${sources.findIndex((e) => e.document_id === s.document_id && e.location === s.location && e.quote === s.quote)}`,
      ),
    })),
  }
}
function safeUrl(value?: string) {
  try {
    const url = new URL(value ?? '')
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}
async function pages<T>(path: string): Promise<T[]> {
  const rows: T[] = []
  for (let offset = 0; ; offset += 100) {
    const page = await request<T[]>(`${path}?limit=100&offset=${offset}`)
    rows.push(...page)
    if (page.length < 100) return rows
  }
}
const companyId = (name: string) => encodeURIComponent(name)
export function createHttpServices(): Services {
  let filingLoad: Promise<Filing[]> | undefined, memoLoad: Promise<Memo[]> | undefined
  let sequence = 0
  const tasks = new Map<string, AnalysisTask>(),
    reports = new Map<string, ReviewReport>()
  const loadFilings = () =>
    (filingLoad ??= (async () => {
      const rows = await pages<FilingRow>('/filings')
      return Promise.all(
        rows.map(async (f): Promise<Filing> => {
          const versions = await pages<VersionRow>(`/filings/${f.id}/versions`)
          const bodies = await Promise.all(
            versions.map((v) => request<VersionRow>(`/filings/${f.id}/versions/${v.version}`)),
          )
          return {
            id: f.id,
            companyId:
              f.corp_code ??
              (f.receipt_no.startsWith('SEC:')
                ? f.receipt_no.split(':').slice(0, 2).join(':')
                : companyId(f.company_name)),
            isCorrection: f.is_correction ?? false,
            originReceiptNo: f.origin_receipt_no ?? null,
            receiptNo: f.receipt_no,
            title: f.title ?? f.filing_type,
            filingType: f.filing_type,
            filedAt: f.filed_at,
            currentVersion: Math.max(0, ...versions.map((v) => v.version)),
            eventGroup: f.receipt_no,
            sourceUrl: disclosureUrl(f.receipt_no),
            versions: bodies.map((v) => ({
              version: v.version,
              rawContent: v.raw_content ?? '',
              createdAt: v.created_at,
            })),
          }
        }),
      )
    })().catch((error) => {
      filingLoad = undefined
      throw error
    }))
  async function loadMemo(m: MemoRow): Promise<Memo> {
    const versions = await pages<VersionRow>(`/memos/${m.id}/versions`)
    const bodies = await Promise.all(
      versions.map((v) => request<VersionRow>(`/memos/${m.id}/versions/${v.version}`)),
    )
    return {
      id: m.id,
      companyName: m.company_name,
      title: m.title,
      currentVersion: m.current_version,
      createdAt: m.created_at,
      updatedAt: m.updated_at,
      versions: bodies.map((v) => ({
        version: v.version,
        content: v.content ?? '',
        createdAt: v.created_at,
        originalFilename: v.original_filename ?? null,
        sizeBytes: v.size_bytes ?? null,
        contentHash: v.content_hash ?? null,
      })),
    }
  }
  const loadMemos = () =>
    (memoLoad ??= pages<MemoRow>('/memos')
      .then((rows) => Promise.all(rows.map(loadMemo)))
      .catch((error) => {
        memoLoad = undefined
        throw error
      }))
  async function mapTask(row: TaskRow): Promise<AnalysisTask> {
    const filings = await loadFilings(),
      memos = await loadMemos()
    const filing = filings.find((f) => f.receiptNo === row.disclosure_receipt_no)
    const name = row.company_name_snapshot ?? memos.find((m) => m.id === row.memo_id)?.companyName
    const perspectives = await request<
      {
        perspective_type: Perspective['type']
        selection_reason: string
        question: string
        status: Perspective['status']
        result_json: { findings?: string } | null
        failure_code: string | null
      }[]
    >(`/analyses/${row.task_id}/perspectives`)
    const task: AnalysisTask = {
      id: row.task_id,
      companyId: filing?.companyId ?? (name ? companyId(name) : ''),
      filingId: filing?.id ?? '',
      disclosureReceiptNo: row.disclosure_receipt_no,
      memoId: row.memo_id,
      baseMemoVersion: row.base_memo_version,
      status: row.status,
      currentStage: row.current_stage,
      createdAt: row.created_at,
      startedAt: row.started_at,
      completedAt: row.completed_at,
      asOf: filing?.filedAt ?? row.created_at,
      hasWarnings: row.has_warnings,
      errorStage: row.error_stage,
      errorMessage: row.error_code,
      sequence: ++sequence,
      perspectives: perspectives.map((p) => ({
        type: p.perspective_type,
        selected: true,
        selectionReason: p.selection_reason,
        question: p.question,
        status: p.status,
        result: p.result_json?.findings ?? p.failure_code,
      })),
    }
    tasks.set(task.id, task)
    return task
  }
  async function reportFor(taskId: string) {
    if (reports.has(taskId)) return reports.get(taskId)
    const row = await request<ReportRow | null>(`/analyses/${taskId}/report`)
    if (row) {
      const report = mapReport(row)
      reports.set(taskId, report)
      return report
    }
  }
  const reads = new Set<string>()
  const readStorageKey = () => `disclosure-check.reads.${currentUser.value?.id ?? ''}`
  return {
    companies: {
      async list() {
        const [filings, favorites] = await Promise.all([
          pages<FilingRow>('/filings'),
          pages<{ corp_code: string; company_name: string; stock_code: string }>('/favorites'),
        ])
        const values = new Map<string, Company>()
        for (const row of filings) {
          const id = row.corp_code ?? companyId(row.company_name)
          values.set(id, {
            id,
            name: row.company_name,
            code: '',
            sector: '',
            initials: row.company_name.slice(0, 1),
            description: '',
            favorite: false,
          })
        }
        for (const row of favorites)
          values.set(row.corp_code, {
            id: row.corp_code,
            name: row.company_name,
            code: row.stock_code,
            sector: '',
            initials: row.company_name.slice(0, 1),
            description: '',
            favorite: true,
          })
        return [...values.values()].sort((a, b) => a.name.localeCompare(b.name))
      },
    },
    filings: {
      list: loadFilings,
      invalidate() {
        filingLoad = undefined
      },
    },
    memos: {
      list: loadMemos,
      async get(id) {
        return loadMemo(await request<MemoRow>(`/memos/${id}`))
      },
      async edit(id, content, baseVersion) {
        await readMemoFile(new File([content], 'memo.txt', { type: 'text/plain' }))
        const row = await request<MemoRow>(`/memos/${id}/versions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content, base_version: baseVersion }),
        })
        memoLoad = undefined
        return loadMemo(row)
      },
      async remove(id) {
        await request<void>(`/memos/${id}`, { method: 'DELETE' })
        memoLoad = undefined
      },
      async upload(file, title, companyId) {
        await readMemoFile(file)
        const form = new FormData()
        form.append('file', file)
        if (title !== undefined) form.append('title', title)
        if (companyId !== undefined) form.append('company_id', companyId)
        const row = await request<MemoRow>('/memos', { method: 'POST', body: form })
        const memo = await loadMemo(row)
        memoLoad = undefined
        return memo
      },
    },
    analyses: {
      async list() {
        return Promise.all((await pages<TaskRow>('/analyses')).map(mapTask))
      },
      async reports() {
        const rows = await pages<TaskRow>('/analyses')
        const values = await Promise.all(
          rows
            .filter((t) =>
              ['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'SAVE_FAILED'].includes(t.status),
            )
            .map((t) => reportFor(t.task_id)),
        )
        return values.filter((r): r is ReviewReport => !!r)
      },
      async start(input) {
        const filing = (await loadFilings()).find((f) => f.id === input.filingId)
        if (!filing) throw new Error('분석할 공시를 확인할 수 없습니다.')
        const receiptNo = filing.receiptNo
        if (
          !receiptNo ||
          !/^(?:[0-9]{14}|SEC:[0-9]{1,10}:[0-9]{10}-[0-9]{2}-[0-9]{6})$/.test(receiptNo)
        )
          throw new Error('유효한 공시 접수번호가 필요합니다.')
        let id: string
        try {
          const row = await request<{ task_id: string }>('/analyses', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              memo_id: input.memoId,
              memo_version: input.memoVersion,
              disclosure_receipt_no: receiptNo,
            }),
          })
          id = row.task_id
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 409 || !error.existingTaskId)
            throw error
          id = error.existingTaskId
        }
        return mapTask(await request<TaskRow>(`/analyses/${id}`))
      },
      subscribe(listener, onError) {
        let stopped = false,
          timer: ReturnType<typeof setTimeout>
        async function poll() {
          try {
            for (const existing of [...tasks.values()]) {
              if (
                !['CREATED', 'QUEUED', 'RUNNING', 'SAVING', 'SAVE_FAILED'].includes(existing.status)
              )
                continue
              const task = await mapTask(await request<TaskRow>(`/analyses/${existing.id}`))
              const report = ['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'SAVE_FAILED'].includes(
                task.status,
              )
                ? await reportFor(task.id)
                : undefined
              if (!stopped) listener({ task, ...(report ? { report } : {}) })
            }
          } catch (error) {
            if (!stopped) onError?.(error instanceof Error ? error.message : '진행 조회 실패')
          } finally {
            if (!stopped && hasSession()) timer = setTimeout(poll, 2000)
          }
        }
        timer = setTimeout(poll, 2000)
        return () => {
          stopped = true
          clearTimeout(timer)
        }
      },
    },
    reads: {
      async list() {
        try {
          const values: unknown = JSON.parse(localStorage.getItem(readStorageKey()) ?? '[]')
          if (Array.isArray(values)) for (const v of values) if (typeof v === 'string') reads.add(v)
        } catch {
          /* 읽음 저장소 오류는 자료 조회를 막지 않습니다. */
        }
        return [...reads]
      },
      async mark(ref) {
        const key = readKey(ref)
        reads.add(key)
        try {
          localStorage.setItem(readStorageKey(), JSON.stringify([...reads]))
        } catch {
          /* 현재 화면의 읽음 상태는 유지합니다. */
        }
        return key
      },
    },
  }
}

export function signup(email: string, password: string, name: string, role: 'RA' | 'ANALYST' = 'ANALYST') {
  return request<CurrentUser>(
    '/auth/signup',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name, role }),
    },
    false,
  )
}
export async function changeName(name: string) {
  currentUser.value = await request<CurrentUser>('/users/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}
export async function deleteAccount(password: string) {
  await request<void>('/users/me', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  logout()
}
export async function changePassword(currentPassword: string, newPassword: string) {
  await request<void>('/users/me/password', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  // 서버가 모든 기존 토큰을 무효화하므로 현재 탭의 인증도 함께 지웁니다.
  logout()
}

export async function downloadReport(taskId: string, extension: 'md' | 'pdf') {
  const blob = await request<Blob>(`/analyses/${taskId}/report.${extension}`, {}, true, 'blob')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `report-${taskId}.${extension}`
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
