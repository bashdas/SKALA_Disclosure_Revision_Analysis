import { toast as notification, notifyError } from '../lib/notifications'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
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
  const drawerLoading = ref(false)
  let drawerRequest = 0
  watch(
    drawer,
    (doc) => {
      if (!doc) {
        drawerRequest++
        drawerLoading.value = false
      }
    },
    { flush: 'sync' },
  )
  const syncError = ref('')
  let initialization: Promise<void> | null = null,
    unsubscribe: (() => void) | null = null
  const savedReports = computed(() => reports.value.filter((r) => r.savedAt !== null))
  function applyTask(task: AnalysisTask) {
    const i = tasks.value.findIndex((t) => t.id === task.id)
    const previous = tasks.value[i]
    if (previous && task.sequence < previous.sequence) return
    if (i < 0) tasks.value.unshift(task)
    else tasks.value[i] = task
    if (!previous || previous.status === task.status) return
    const completed = ['COMPLETED', 'COMPLETED_WITH_WARNINGS']
    if (completed.includes(task.status) && !completed.includes(previous.status))
      notification.success('분석이 완료되었습니다.', {
        description: companyName(task.companyId),
        id: 'analysis:' + task.id,
      })
    else if (task.status === 'FAILED' || task.status === 'SAVE_FAILED')
      notification.error(
        task.status === 'FAILED' ? '분석에 실패했습니다.' : '보고서를 저장하지 못했습니다.',
        {
          description: task.errorMessage ?? companyName(task.companyId),
          id: 'analysis:' + task.id,
        },
      )
    else if (task.status === 'CANCELLED')
      notification.info('분석이 취소되었습니다.', { id: 'analysis:' + task.id })
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
        unsubscribe ??= services.analyses.subscribe(
          (event) => {
            syncError.value = ''
            applyTask(event.task)
            if (event.report) {
              const i = reports.value.findIndex((r) => r.id === event.report!.id)
              if (i < 0) reports.value.push(event.report)
              else reports.value[i] = event.report
            }
          },
          (message) => {
            syncError.value = message
            notifyError(message)
          },
        )
        ready.value = true
      } catch (e) {
        error.value = e instanceof Error ? e.message : '자료를 불러오지 못했습니다.'
        notifyError(e)
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
  function memosForCompany(companyId: string) {
    const company = companies.value.find((c) => c.id === companyId)
    if (!company) return []
    return memos.value.filter(
      (m) => m.companyName?.normalize('NFC') === company.name.normalize('NFC'),
    )
  }
  function countUnread(companyId: string, kind: 'filing' | 'memo' | 'report') {
    if (kind === 'filing')
      return filings.value.filter(
        (f) => f.companyId === companyId && unread({ kind, id: f.id, version: f.currentVersion }),
      ).length
    if (kind === 'memo')
      return memosForCompany(companyId).filter((m) =>
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
  async function openMemo(id: string, version?: number, paragraph?: number | null) {
    const request = ++drawerRequest
    drawerLoading.value = false
    let memo = memos.value.find((m) => m.id === id)
    if (!memo) {
      drawerLoading.value = true
      drawer.value = { title: '메모', subtitle: '', content: '', memoId: id }
      try {
        memo = await services.memos.get(id)
        if (request !== drawerRequest) return
      } catch (e) {
        if (request === drawerRequest) {
          syncError.value = e instanceof Error ? e.message : '메모 조회 실패'
          notifyError(e)
          drawer.value = null
        }
        return
      } finally {
        if (request === drawerRequest) drawerLoading.value = false
      }
    }
    const v = memo.versions.find((v) => v.version === (version ?? memo.currentVersion))
    if (!v) {
      drawer.value = null
      syncError.value = '요청한 메모 버전을 찾지 못했습니다.'
      notifyError(syncError.value)
      return
    }
    drawer.value = {
      title: memo.title,
      subtitle: `${memo.companyName ?? '기업 미확정'} , 사내 메모`,
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
      subtitle: filing.receiptNo ? `접수번호 ${filing.receiptNo}` : '접수번호 미확인',
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
      subtitle: '분석 근거 인용',
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
  async function deleteMemo(id: string) {
    await services.memos.remove(id)
    memos.value = memos.value.filter((m) => m.id !== id)
    if (drawer.value?.memoId === id) drawer.value = null
    notification.success('메모를 삭제했습니다.')
  }
  async function start(input: StartAnalysisInput) {
    if (busy.value) return null
    busy.value = true
    try {
      const task = await services.analyses.start(input)
      applyTask(task)
      if (['COMPLETED', 'COMPLETED_WITH_WARNINGS'].includes(task.status))
        notification.info('기존 분석 결과를 불러왔습니다.')
      else
        notification.success('분석을 시작했습니다.', { description: companyName(task.companyId) })
      return task
    } finally {
      busy.value = false
    }
  }
  async function refresh() {
    services.filings.invalidate()
    const [c, f] = await Promise.all([services.companies.list(), services.filings.list()])
    const merged = new Map(companies.value.map(company => [company.id, { ...company, favorite: false }]))
    for (const company of c) {
      const previous = merged.get(company.id)
      merged.set(company.id, {
        ...previous,
        ...company,
        favorite: !!company.favorite,
        code: company.code || previous?.code || '',
        sector: company.sector || previous?.sector || '',
        description: company.description || previous?.description || '',
      })
    }
    companies.value = [...merged.values()]
    filings.value = f
  }
  function dispose() {
    unsubscribe?.()
    unsubscribe = null
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
    drawerLoading,
    toast,
    initialize,
    refresh,
    companyName,
    memosForCompany,
    unread,
    countUnread,
    markRead,
    openMemo,
    openFiling,
    openEvidence,
    upload,
    deleteMemo,
    start,
    dispose,
    syncError,
  }
})
