import type { Services } from './contracts'
import { readKey } from './contracts'
import { readMemoFile } from './upload'
import { companies, filings, memos, seedTasks, buildReport, perspectives } from '../fixtures/cases'
import { activeStatuses, stages } from '../types/domain'
import type { AnalysisTask, AnalysisEvent, ReviewReport } from '../types/domain'

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value))
export function createMockServices(
  options: {
    empty?: boolean
    failLoad?: boolean
    latency?: number
    stepMs?: number
    storage?: Storage | null
  } = {},
): Services {
  const state = {
    companies: copy(options.empty ? [] : companies),
    filings: copy(options.empty ? [] : filings),
    memos: copy(options.empty ? [] : memos),
    ...(options.empty
      ? { tasks: [] as AnalysisTask[], reports: [] as ReviewReport[] }
      : seedTasks()),
  }
  const listeners = new Set<(event: AnalysisEvent) => void>()
  const wait = (ms = options.latency ?? 120) => new Promise<void>((r) => setTimeout(r, ms))
  const stepMs = options.stepMs ?? 650
  let storage: Storage | null = options.storage ?? null
  if (options.storage === undefined) {
    try {
      storage = window.localStorage
    } catch {
      /* ephemeral reads remain available */
    }
  }
  let readKeys: string[] = []
  try {
    const parsed: unknown = JSON.parse(storage?.getItem('disclosure-check.reads.v1') ?? '[]')
    if (Array.isArray(parsed)) readKeys = parsed.filter((v): v is string => typeof v === 'string')
  } catch {
    /* corrupt storage cannot block the workspace */
  }
  async function list<T>(items: T[]): Promise<T[]> {
    await wait()
    if (options.failLoad) throw new Error('샘플 자료를 불러오지 못했습니다. 다시 시도해 주세요.')
    return copy(items)
  }
  function emit(task: AnalysisTask) {
    task.sequence++
    const report = state.reports.find((r) => r.taskId === task.id)
    for (const fn of listeners)
      fn({ task: copy(task), ...(report ? { report: copy(report) } : {}) })
  }
  function run(task: AnalysisTask) {
    stages.forEach((stage, index) =>
      setTimeout(
        () => {
          if (task.status === 'FAILED') return
          task.status = stage === 'REPORT_SAVE' ? 'SAVING' : 'RUNNING'
          task.currentStage = stage
          task.startedAt ??= new Date().toISOString()
          if (task.scenario === 'analysis-failure' && stage === 'INPUT_COLLECTION') {
            task.status = 'FAILED'
            task.errorStage = stage
            task.errorMessage = '시연 시나리오: 필수 자료 조회에 실패했습니다.'
            task.completedAt = new Date().toISOString()
            emit(task)
            return
          }
          if (stage === 'PERSPECTIVE_ANALYSIS')
            task.perspectives.forEach((p) => {
              if (p.selected) p.status = 'RUNNING'
            })
          if (stage === 'REPORT_GENERATION') {
            task.perspectives.forEach((p) => {
              if (!p.selected) return
              const incomplete =
                p.type === 'FINANCE' &&
                (task.scenario === 'evidence-gap' || task.scenario === 'limit')
              p.status = incomplete
                ? task.scenario === 'limit'
                  ? 'LIMIT_REACHED'
                  : 'INSUFFICIENT_EVIDENCE'
                : 'COMPLETED'
              p.result = incomplete
                ? '확보된 자료로 결론을 확정할 수 없어 판단을 보류합니다.'
                : p.type === 'FINANCE'
                  ? '계약금액·기존 손실·실제 현금 부담을 구분하고 중복 반영을 점검합니다.'
                  : p.type === 'EXTERNAL_RISK'
                    ? '제재와 계약 분쟁에 대한 주장·확정 사항·미확인 조건을 구분합니다.'
                    : '기존 성장·수주 논리와 변경 사실을 비교하고 정량 가정은 추가 확인합니다.'
            })
            state.reports.push(
              buildReport(
                task,
                state.memos.find((m) => m.id === task.memoId)!,
                state.filings.find((f) => f.id === task.filingId)!,
              ),
            )
          }
          emit(task)
        },
        stepMs * (index + 1),
      ),
    )
    setTimeout(
      () => {
        if (task.status === 'FAILED') return
        const report = state.reports.find((r) => r.taskId === task.id)!
        if (task.scenario === 'save-failure') {
          task.status = 'SAVE_FAILED'
          task.errorStage = 'REPORT_SAVE'
          task.errorMessage = '시연 시나리오: 보고서 저장에 실패했습니다. 생성 내용은 유지됩니다.'
        } else {
          report.savedAt = new Date().toISOString()
          task.hasWarnings = report.warnings.length > 0
          task.status = task.hasWarnings ? 'COMPLETED_WITH_WARNINGS' : 'COMPLETED'
          task.completedAt = report.savedAt
        }
        emit(task)
      },
      stepMs * (stages.length + 1),
    )
  }
  return {
    companies: { list: () => list(state.companies) },
    filings: { list: () => list(state.filings) },
    memos: {
      list: () => list(state.memos),
      async upload(file, title, companyId) {
        const company = state.companies.find((c) => c.id === companyId)
        if (companyId !== undefined && !company) throw new Error('등록된 기업을 선택해 주세요.')
        const content = await readMemoFile(file)
        const name = file.name.split(/[\\/]/).pop() || '메모.txt'
        const displayTitle = title === undefined ? name.replace(/\.txt$/i, '') : title.trim()
        if (!displayTitle || displayTitle.length > 500)
          throw new Error('제목은 1~500자로 입력해 주세요.')
        const time = new Date().toISOString()
        const memo = {
          id: `uploaded-${crypto.randomUUID()}`,
          companyName: company?.name ?? null,
          title: displayTitle,
          currentVersion: 1,
          createdAt: time,
          updatedAt: time,
          versions: [
            {
              version: 1,
              content,
              createdAt: time,
              originalFilename: name,
              sizeBytes: file.size,
              contentHash: null,
            },
          ],
        }
        state.memos.unshift(memo)
        await wait()
        return copy(memo)
      },
    },
    analyses: {
      list: () => list(state.tasks),
      reports: () => list(state.reports),
      async start(input) {
        const filing = state.filings.find((f) => f.id === input.filingId),
          memo = state.memos.find((m) => m.id === input.memoId)
        if (!filing || !memo || !memo.versions.some((v) => v.version === input.memoVersion))
          throw new Error('공시와 유효한 기준 메모 버전을 선택해 주세요.')
        const company = state.companies.find((c) => c.id === filing.companyId)!
        if (memo.companyName && memo.companyName !== company.name)
          throw new Error('선택한 공시와 메모의 기업이 다릅니다.')
        const existing = state.tasks.find(
          (t) =>
            t.filingId === filing.id &&
            t.memoId === memo.id &&
            t.baseMemoVersion === input.memoVersion &&
            activeStatuses.includes(t.status),
        )
        if (existing) return copy(existing)
        const task: AnalysisTask = {
          id: crypto.randomUUID(),
          companyId: filing.companyId,
          filingId: filing.id,
          memoId: memo.id,
          baseMemoVersion: input.memoVersion,
          status: 'QUEUED',
          currentStage: 'REQUEST_VALIDATION',
          asOf: filing.companyId === 'lnf' ? '2025-12-29T23:59:59+09:00' : filing.filedAt,
          createdAt: new Date().toISOString(),
          startedAt: null,
          completedAt: null,
          perspectives: perspectives(filing.companyId),
          errorMessage: null,
          errorStage: null,
          hasWarnings: false,
          sequence: 0,
          scenario: input.scenario ?? 'normal',
        }
        state.tasks.unshift(task)
        emit(task)
        run(task)
        await wait()
        return copy(task)
      },
      async retrySave(id) {
        const task = state.tasks.find((t) => t.id === id),
          report = state.reports.find((r) => r.taskId === id)
        if (!task || !report || task.status !== 'SAVE_FAILED')
          throw new Error('저장 실패 상태의 보고서만 다시 저장할 수 있습니다.')
        task.status = 'SAVING'
        emit(task)
        await wait(stepMs)
        report.savedAt = new Date().toISOString()
        task.status = report.warnings.length ? 'COMPLETED_WITH_WARNINGS' : 'COMPLETED'
        task.hasWarnings = report.warnings.length > 0
        task.completedAt = report.savedAt
        task.errorStage = null
        task.errorMessage = null
        emit(task)
        return copy(task)
      },
      subscribe(listener) {
        listeners.add(listener)
        return () => listeners.delete(listener)
      },
    },
    reads: {
      async list() {
        return [...readKeys]
      },
      async mark(ref) {
        const key = readKey(ref)
        if (!readKeys.includes(key)) {
          readKeys.push(key)
          try {
            storage?.setItem('disclosure-check.reads.v1', JSON.stringify(readKeys))
          } catch {
            /* read status still works for this session */
          }
        }
        return key
      },
    },
  }
}
