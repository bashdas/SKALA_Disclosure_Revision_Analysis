import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { services } from '../services'
import { readKey } from '../services/contracts'
import type {
  AnalysisTask,
  Company,
  Evidence,
  Filing,
  Memo,
  ReadReference,
  ReviewReport,
  StartAnalysisInput,
} from '../types/domain'

export interface DrawerDocument {
  title: string
  subtitle: string
  content: string
  location?: string
  publishedAt?: string
  url?: string | null
  readRef?: ReadReference
  paragraph?: number | null
  versions?: number[]
  selectedVersion?: number
  memoId?: string
  filingId?: string
}
export const useWorkspace = defineStore('workspace', () => {
  const companies = ref<Company[]>([]),
    filings = ref<Filing[]>([]),
    memos = ref<Memo[]>([])
  const tasks = ref<AnalysisTask[]>([]),
    reports = ref<ReviewReport[]>([]),
    readKeys = ref<string[]>([])
  const loading = ref(false),
    ready = ref(false),
    error = ref(''),
    drawer = ref<DrawerDocument | null>(null)
  const busy = ref(false),
    toast = ref('')
  let initialization: Promise<void> | null = null,
    unsubscribe: (() => void) | null = null
  const savedReports = computed(() => reports.value.filter((r) => r.savedAt !== null))
  function applyTask(task: AnalysisTask) {
    const i = tasks.value.findIndex((t) => t.id === task.id)
    if (i < 0) tasks.value.unshift(task)
    else if (task.sequence >= tasks.value[i]!.sequence) tasks.value[i] = task
  }
  async function initialize() {
    if (ready.value) return
    if (initialization) return initialization
    loading.value = true
    error.value = ''
    initialization = (async () => {
      try {
        const [c, f, m, t, r, reads] = await Promise.all([
          services.companies.list(),
          services.filings.list(),
          services.memos.list(),
          services.analyses.list(),
          services.analyses.reports(),
          services.reads.list(),
        ])
        companies.value = c
        filings.value = f
        memos.value = m
        tasks.value = t
        reports.value = r
        readKeys.value = reads
        unsubscribe ??= services.analyses.subscribe((event) => {
          applyTask(event.task)
          if (event.report) {
            const i = reports.value.findIndex((r) => r.id === event.report!.id)
            if (i < 0) reports.value.push(event.report)
            else reports.value[i] = event.report
          }
        })
        ready.value = true
      } catch (e) {
        error.value = e instanceof Error ? e.message : '자료를 불러오지 못했습니다.'
      } finally {
        loading.value = false
        initialization = null
      }
    })()
    return initialization
  }
  function companyName(id: string) {
    return companies.value.find((c) => c.id === id)?.name ?? '기업 미확정'
  }
  function unread(ref: ReadReference) {
    return !readKeys.value.includes(readKey(ref))
  }
  function countUnread(companyId: string, kind: 'filing' | 'memo' | 'report') {
    if (kind === 'filing')
      return filings.value.filter(
        (f) => f.companyId === companyId && unread({ kind, id: f.id, version: f.currentVersion }),
      ).length
    if (kind === 'memo')
      return memos.value.filter(
        (m) =>
          m.companyName === companyName(companyId) &&
          unread({ kind, id: m.id, version: m.currentVersion }),
      ).length
    return savedReports.value.filter(
      (r) =>
        tasks.value.find((t) => t.id === r.taskId)?.companyId === companyId &&
        unread({ kind, id: r.id, version: r.version }),
    ).length
  }
  async function markRead(ref: ReadReference) {
    const key = await services.reads.mark(ref)
    if (!readKeys.value.includes(key)) readKeys.value.push(key)
  }
  function openMemo(id: string, version?: number, paragraph?: number) {
    const memo = memos.value.find((m) => m.id === id)
    if (!memo) return
    const v = memo.versions.find((v) => v.version === (version ?? memo.currentVersion))
    if (!v) return
    drawer.value = {
      title: memo.title,
      subtitle: `${memo.companyName ?? '기업 미확정'} · 시연용 사내 메모`,
      content: v.content,
      publishedAt: v.createdAt,
      readRef: { kind: 'memo', id, version: v.version },
      versions: memo.versions.map((v) => v.version),
      selectedVersion: v.version,
      memoId: id,
      paragraph,
    }
  }
  function openFiling(id: string, version?: number) {
    const filing = filings.value.find((f) => f.id === id)
    if (!filing) return
    const v = filing.versions.find((v) => v.version === (version ?? filing.currentVersion))
    if (!v) return
    drawer.value = {
      title: filing.title,
      subtitle: filing.receiptNo
        ? `접수번호 ${filing.receiptNo}`
        : '접수번호 미확인 · 보도 기반 샘플',
      content: v.rawContent,
      publishedAt: v.createdAt,
      url: filing.sourceUrl,
      readRef: { kind: 'filing', id, version: v.version },
      versions: filing.versions.map((v) => v.version),
      selectedVersion: v.version,
      filingId: id,
    }
  }
  function openEvidence(evidence: Evidence) {
    if (evidence.kind === 'memo' && evidence.documentId) {
      openMemo(evidence.documentId, evidence.version ?? undefined, evidence.paragraph ?? undefined)
      return
    }
    drawer.value = {
      title: evidence.title,
      subtitle: '분석 근거 · 시연용 요약',
      content: evidence.context,
      publishedAt: evidence.publishedAt,
      location: evidence.location,
      url: evidence.url,
    }
  }
  async function upload(file: File, title?: string, companyId?: string) {
    const memo = await services.memos.upload(file, title, companyId)
    memos.value.unshift(memo)
    return memo
  }
  async function start(input: StartAnalysisInput) {
    if (busy.value) return null
    busy.value = true
    try {
      const task = await services.analyses.start(input)
      applyTask(task)
      return task
    } finally {
      busy.value = false
    }
  }
  async function retrySave(taskId: string) {
    const task = await services.analyses.retrySave(taskId)
    applyTask(task)
  }
  return {
    companies,
    filings,
    memos,
    tasks,
    reports,
    savedReports,
    readKeys,
    loading,
    ready,
    error,
    busy,
    drawer,
    toast,
    initialize,
    companyName,
    unread,
    countUnread,
    markRead,
    openMemo,
    openFiling,
    openEvidence,
    upload,
    start,
    retrySave,
  }
})
