import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { File as BufferFile } from 'node:buffer'
import { createMockServices } from './mock'
import { readMemoFile, MAX_MEMO_BYTES } from './upload'
import { readKey } from './contracts'
import type { Services } from './contracts'
import type { AnalysisEvent, Scenario } from '../types/domain'

const file = (body: string | Uint8Array, name = '메모.txt', type = 'text/plain') =>
  new BufferFile([body], name, { type }) as unknown as File
class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() {
    return this.values.size
  }
  clear() {
    this.values.clear()
  }
  getItem(key: string) {
    return this.values.get(key) ?? null
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null
  }
  removeItem(key: string) {
    this.values.delete(key)
  }
  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}
describe('메모 입력 경계', () => {
  it('UTF-8 BOM을 제거하고 본문의 공백·줄바꿈은 보존한다', async () => {
    expect(await readMemoFile(file('\uFEFF 첫 문단\n\n둘째 문단 '))).toBe(' 첫 문단\n\n둘째 문단 ')
  })
  it.each([
    [file('내용', '메모.pdf', 'application/pdf'), 'UTF-8 .txt'],
    [file('내용', '메모.txt', 'text/html'), 'UTF-8 .txt'],
    [file(' \n\t'), '비어'],
    [file('내용\0'), 'NUL'],
    [file(new Uint8Array([0xff, 0xfe, 0xff])), 'UTF-8로 저장'],
    [file('x'.repeat(MAX_MEMO_BYTES + 1)), '5 MiB'],
  ])('부적합한 업로드를 거부한다: %s', async (input, message) => {
    await expect(readMemoFile(input)).rejects.toThrow(message)
  })
})
describe('샘플 업무 서비스의 보존·상태 계약', () => {
  let service: Services
  let storage: Storage
  beforeEach(() => {
    vi.useFakeTimers()
    storage = new MemoryStorage()
    service = createMockServices({ latency: 0, stepMs: 5, storage })
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })
  async function resolve<T>(promise: Promise<T>) {
    await vi.runAllTimersAsync()
    return promise
  }
  async function start(scenario: Scenario = 'normal') {
    return resolve(
      service.analyses.start({
        filingId: 'filing-lnf',
        memoId: 'memo-lnf',
        memoVersion: 1,
        scenario,
      }),
    )
  }
  it('동시 중복 요청은 한 작업으로 합치고 기준 버전·원본을 보존한다', async () => {
    const original = await resolve(service.memos.list())
    const input = { filingId: 'filing-lnf', memoId: 'memo-lnf', memoVersion: 1 }
    const a = service.analyses.start(input),
      b = service.analyses.start(input)
    await vi.runAllTimersAsync()
    const [one, two] = await Promise.all([a, b])
    expect(one.id).toBe(two.id)
    const tasks = await resolve(service.analyses.list())
    expect(tasks).toHaveLength(5)
    expect(tasks.find((t) => t.id === one.id)?.baseMemoVersion).toBe(1)
    expect(await resolve(service.memos.list())).toEqual(original)
    const report = (await resolve(service.analyses.reports())).find((r) => r.taskId === one.id)!
    expect(report.findings[0]?.beforeText).toBe(original[0]!.versions[0]!.content.split('\n\n')[0])
    expect(report.savedAt).not.toBeNull()
  })
  it('저장 실패 후 생성 내용을 유지하며 저장만 재시도한다', async () => {
    const task = await start('save-failure')
    expect((await resolve(service.analyses.list())).find((t) => t.id === task.id)?.status).toBe(
      'SAVE_FAILED',
    )
    const before = (await resolve(service.analyses.reports())).find((r) => r.taskId === task.id)!
    expect(before.savedAt).toBeNull()
    const retried = await resolve(service.analyses.retrySave(task.id))
    const after = (await resolve(service.analyses.reports())).find((r) => r.taskId === task.id)!
    expect(retried.status).toBe('COMPLETED_WITH_WARNINGS')
    expect(after.savedAt).not.toBeNull()
    expect(after.findings).toEqual(before.findings)
    expect(after.generatedAt).toBe(before.generatedAt)
    expect(await resolve(service.analyses.list())).toHaveLength(5)
    await expect(service.analyses.retrySave(task.id)).rejects.toThrow('저장 실패 상태')
  })
  it.each(['evidence-gap', 'limit'] as const)(
    '근거 부족·한도 도달을 영향 없음과 구분한다: %s',
    async (scenario) => {
      const task = await start(scenario)
      const final = (await resolve(service.analyses.list())).find((t) => t.id === task.id)!
      const report = (await resolve(service.analyses.reports())).find((r) => r.taskId === task.id)!
      expect(final.status).toBe('COMPLETED_WITH_WARNINGS')
      expect(report.findings[0]?.impactType).toBe('HOLD')
      expect(final.perspectives.find((p) => p.type === 'FINANCE')?.status).toBe(
        scenario === 'limit' ? 'LIMIT_REACHED' : 'INSUFFICIENT_EVIDENCE',
      )
      expect(final.perspectives.find((p) => p.type === 'EXTERNAL_RISK')?.selected).toBe(false)
    },
  )
  it('필수 조회 실패를 완료로 처리하거나 보고서를 생성하지 않는다', async () => {
    const task = await start('analysis-failure')
    const final = (await resolve(service.analyses.list())).find((t) => t.id === task.id)!
    expect(final.status).toBe('FAILED')
    expect(final.errorStage).toBe('INPUT_COLLECTION')
    expect(
      (await resolve(service.analyses.reports())).find((r) => r.taskId === task.id),
    ).toBeUndefined()
  })
  it('업로드는 기업 미확정 v1으로 추가하고 기존 메모를 바꾸지 않는다', async () => {
    const original = await resolve(service.memos.list())
    const memo = await resolve(
      service.memos.upload(file('  새 가정\n\n검토 필요  '), '  업로드 메모  '),
    )
    expect(memo.companyName).toBeNull()
    expect(memo.currentVersion).toBe(1)
    expect(memo.title).toBe('업로드 메모')
    expect(memo.versions[0]?.content).toBe('  새 가정\n\n검토 필요  ')
    expect((await resolve(service.memos.list())).filter((m) => m.id !== memo.id)).toEqual(original)
  })
  it('종목에 연결한 업로드 메모는 다른 기업에 사용되지 않고 시연 판정을 보류한다', async () => {
    const memo = await resolve(service.memos.upload(file('새 검토 가정'), '종목 메모', 'lnf'))
    expect(memo.companyName).toBe('엘앤에프')
    await expect(
      service.analyses.start({ filingId: 'filing-shi-1', memoId: memo.id, memoVersion: 1 }),
    ).rejects.toThrow('기업이 다릅니다')
    const task = await resolve(
      service.analyses.start({ filingId: 'filing-lnf', memoId: memo.id, memoVersion: 1 }),
    )
    const report = (await resolve(service.analyses.reports())).find((r) => r.taskId === task.id)!
    expect(report.findings.every((f) => f.impactType === 'HOLD')).toBe(true)
    await expect(service.memos.upload(file('내용'), undefined, 'unknown-company')).rejects.toThrow(
      '등록된 기업',
    )
  })
  it('기업이 다른 메모와 없는 버전은 분석 입력으로 거부한다', async () => {
    await expect(
      service.analyses.start({ filingId: 'filing-lnf', memoId: 'memo-shi', memoVersion: 1 }),
    ).rejects.toThrow('기업이 다릅니다')
    await expect(
      service.analyses.start({ filingId: 'filing-lnf', memoId: 'memo-lnf', memoVersion: 9 }),
    ).rejects.toThrow('유효한')
  })
  it('읽음을 문서·버전별로 저장하고 서비스 재생성 후에도 유지한다', async () => {
    const ref = { kind: 'memo' as const, id: 'memo-lnf', version: 1 }
    await service.reads.mark(ref)
    await service.reads.mark(ref)
    expect(await service.reads.list()).toEqual([readKey(ref)])
    const fresh = createMockServices({ latency: 0, storage })
    expect(await fresh.reads.list()).toEqual([readKey(ref)])
    expect(await fresh.reads.list()).not.toContain(readKey({ ...ref, version: 2 }))
    expect(await fresh.reads.list()).not.toContain(
      readKey({ kind: 'report', id: 'memo-lnf', version: 1 }),
    )
  })
  it('손상된 읽음 저장소나 저장소 차단 때문에 앱이 실패하지 않는다', async () => {
    storage.setItem('disclosure-check.reads.v1', '{broken')
    expect(await createMockServices({ storage }).reads.list()).toEqual([])
    const blocked = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    } as unknown as Storage
    const fresh = createMockServices({ storage: blocked })
    await fresh.reads.mark({ kind: 'filing', id: 'x', version: 1 })
    expect(await fresh.reads.list()).toHaveLength(1)
  })
  it('관점 결과와 단계 이벤트는 순서가 증가하며 저장 시점을 구분한다', async () => {
    const events: AnalysisEvent[] = []
    const stop = service.analyses.subscribe((e) => events.push(e))
    await start()
    stop()
    expect(events.map((e) => e.task.sequence)).toEqual(events.map((_, i) => i + 1))
    expect(events.find((e) => e.task.status === 'SAVING')?.report?.savedAt).toBeNull()
    expect(events.at(-1)?.report?.savedAt).not.toBeNull()
  })
})
