<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ArrowLeft,
  FileText,
  StickyNote,
  Sparkles,
  ArrowUpRight,
  Check,
  Activity,
  Trash2,
} from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date, disclosureUrl } from '../lib/format'
import { request } from '../services/http'
import {
  koreaDate,
  searchDisclosures,
  registerDisclosure,
  unregisterDisclosure,
  type DisclosureRow,
} from '../services/catalog'
import type { Filing } from '../types/domain'
import AnalysisLauncher from '../components/AnalysisLauncher.vue'
import EmptyState from '../components/EmptyState.vue'
import MemoUpload from '../components/MemoUpload.vue'
import CompanyAnalysisHistory from '../components/CompanyAnalysisHistory.vue'
const store = useWorkspace(),
  route = useRoute(),
  preferredFiling = ref(''),
  memoSearch = ref('')
const company = computed(() => store.companies.find((c) => c.id === route.params.companyId))
const tab = computed(() =>
  ['filings', 'memos', 'reports', 'history'].includes(String(route.query.tab))
    ? String(route.query.tab)
    : 'filings',
)
const rows = ref<DisclosureRow[]>([]),
  loading = ref(false),
  error = ref(''),
  hasMore = ref(true),
  page = ref(1),
  search = ref(''),
  busy = ref('')
const start = ref(koreaDate(new Date(Date.now() - 90 * 86400000))),
  end = ref(koreaDate())
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | undefined,
  timer: ReturnType<typeof setInterval>,
  debounce: ReturnType<typeof setTimeout>,
  generation = 0
const companyFilings = computed<Filing[]>(() =>
  rows.value.map((row) => {
    const saved = store.filings.find((f) => f.receiptNo === row.receipt_no)
    return (
      saved ?? {
        id: row.receipt_no,
        companyId: String(route.params.companyId),
        receiptNo: row.receipt_no,
        title: row.report_name,
        filingType: row.is_correction ? '정정공시' : '신규공시',
        filedAt: row.filed_at,
        currentVersion: 1,
        eventGroup: row.receipt_no,
        sourceUrl: disclosureUrl(row.receipt_no),
        isCorrection: row.is_correction,
        originReceiptNo: null,
        versions: [],
      }
    )
  }),
)
async function load(reset = false) {
  if (!reset && (loading.value || !hasMore.value)) return
  if (reset) {
    generation++
    rows.value = []
    page.value = 1
    hasMore.value = true
  }
  const current = generation
  loading.value = true
  error.value = ''
  try {
    const code = String(route.params.companyId)
    if (!store.companies.some((c) => c.id === code)) {
      const data = await request<{
        items: { corp_code: string; company_name: string; stock_code: string }[]
      }>(`/disclosures/companies?query=${code}`)
      const c = data.items.find((c) => c.corp_code === code)
      if (c)
        store.companies.push({
          id: code,
          name: c.company_name,
          code: c.stock_code,
          sector: '',
          initials: c.company_name.slice(0, 1),
          description: '',
        })
    }
    const result = await searchDisclosures({
      company: code,
      start: start.value,
      end: end.value,
      page: page.value,
      query: search.value,
    })
    if (current !== generation) return
    rows.value = [
      ...new Map([...rows.value, ...result.items].map((r) => [r.receipt_no, r])).values(),
    ]
    hasMore.value = result.has_more
    page.value = result.next_page ?? page.value + 1
  } catch (e) {
    if (current === generation) error.value = e instanceof Error ? e.message : '공시 조회 실패'
  } finally {
    if (current === generation) {
      loading.value = false
      await nextTick()
      if (
        !error.value &&
        hasMore.value &&
        sentinel.value &&
        sentinel.value.getBoundingClientRect().top < innerHeight + 200
      )
        void load()
    }
  }
}
async function selectFiling(filing: Filing, analyze = false) {
  if (busy.value || !filing.receiptNo) return
  busy.value = filing.id
  error.value = ''
  try {
    const existing = store.filings.find((f) => f.receiptNo === filing.receiptNo)
    const registered = existing ?? (await registerDisclosure(filing.receiptNo))
    await store.refresh()
    if (analyze) preferredFiling.value = registered.id
    else store.openFiling(registered.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '공시를 불러오지 못했습니다.'
  } finally {
    busy.value = ''
  }
}
async function deleteMemo(id:string, title:string) {
  if(!window.confirm(`‘${title}’ 메모를 삭제할까요? 기존 분석의 기준 원문은 보존됩니다.`))return
  try { await store.deleteMemo(id) }
  catch(e) { error.value=e instanceof Error?e.message:'메모 삭제 실패' }
}
async function remove(filing: Filing) {
  try {
    await unregisterDisclosure(filing.id)
    await store.refresh()
    if (preferredFiling.value === filing.id) preferredFiling.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '등록 해제 실패'
  }
}
watch(
  () => route.params.companyId,
  () => {
    preferredFiling.value = ''
    void load(true)
  },
  { immediate: true },
)
watch([search, start, end], () => {
  clearTimeout(debounce)
  debounce = setTimeout(() => void load(true), 350)
})
watch(sentinel, (el) => {
  if (el) observer?.observe(el)
})
onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) void load()
    },
    { rootMargin: '200px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
  timer = setInterval(() => {
    if (!loading.value) void load(true)
  }, 60000)
})
onBeforeUnmount(() => {
  generation++
  observer?.disconnect()
  clearTimeout(debounce)
  clearInterval(timer)
})
const companyMemos = computed(() =>
  store.memos.filter((m) => m.companyName === company.value?.name || m.companyName === null),
)
const filteredMemos = computed(() =>
  companyMemos.value.filter((m) => m.title.includes(memoSearch.value)),
)
const companyTasks = computed(() => store.tasks.filter((t) => t.companyId === company.value?.id))
const companyReports = computed(() =>
  store.savedReports.filter(
    (r) => store.tasks.find((t) => t.id === r.taskId)?.companyId === company.value?.id,
  ),
)
const tabs = computed(() => [
  { id: 'filings', name: '공시', icon: FileText, count: companyFilings.value.length },
  { id: 'memos', name: '메모 관리', icon: StickyNote, count: companyMemos.value.length },
  { id: 'reports', name: 'AI 보고서', icon: Sparkles, count: companyReports.value.length },
  { id: 'history', name: '분석 이력', icon: Activity, count: companyTasks.value.length },
])
</script>
<template>
  <section v-if="company" class="company-workspace" aria-labelledby="company-title">
    <header class="company-workspace-header">
      <RouterLink to="/companies" class="back-link"><ArrowLeft :size="15" /> 기업 목록</RouterLink>
      <div class="company-detail-heading">
        <span class="company-logo" :class="company.id">{{ company.initials }}</span>
        <div>
          <p class="eyebrow">{{ [company.sector, company.code].filter(Boolean).join(', ') }}</p>
          <h1 id="company-title">{{ company.name }}</h1>
        </div>
      </div>
    </header>
    <nav class="tabs" aria-label="기업 자료 종류">
      <RouterLink
        v-for="item in tabs"
        :key="item.id"
        :to="{ query: { ...route.query, tab: item.id } }"
        :class="{ selected: tab === item.id }"
        :aria-current="tab === item.id ? 'page' : undefined"
        ><component :is="item.icon" :size="16" />{{ item.name
        }}<span>{{ item.count }}</span></RouterLink
      >
    </nav>
    <p v-if="error && tab!=='filings'" class="inline-warning" role="alert">{{error}}</p>
    <div class="detail-layout">
      <section class="document-section" aria-label="기업 자료">
        <template v-if="tab === 'filings'">
          <div class="list-heading">
            <h2>공시 업데이트</h2>
            <span class="small muted">최신순 , {{ companyFilings.length }}건</span>
          </div>
          <form class="list-heading" @submit.prevent="load(true)">
            <label class="sr-only" for="filing-search">공시 검색</label
            ><input
              id="filing-search"
              v-model="search"
              class="compact-search"
              type="search"
              placeholder="공시 검색"
              maxlength="100"
            />
            <label>시작일<input v-model="start" type="date" :max="end" /></label
            ><label
              >종료일<input v-model="end" type="date" :min="start" :max="koreaDate()"
            /></label>
            <button class="text-button" type="submit" :disabled="loading">검색</button>
          </form>
          <p v-if="error" class="inline-warning" role="alert">{{ error }}</p>
          <article v-for="filing in companyFilings" :key="filing.id" class="document-row">
            <span class="document-icon"><FileText :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">{{ filing.filingType }}</span
                ><span
                  v-if="
                    store.unread({ kind: 'filing', id: filing.id, version: filing.currentVersion })
                  "
                  class="new-dot"
                  >NEW</span
                ><span v-else class="read-label"><Check :size="12" /> 확인함</span>
              </div>
              <button
                class="document-title"
                :disabled="!!busy"
                @click="selectFiling(filing, true)"
              >
                {{ filing.title }}
              </button>
              <p class="small muted">
                {{ date(filing.filedAt) }} <span class="dot-separator">,</span>
                {{ filing.receiptNo ?? '접수번호 미확인' }}
              </p>
              <div class="row-actions">
                <button class="text-button" :disabled="!!busy" @click="selectFiling(filing)">
                  내용 확인 <ArrowUpRight :size="13" /></button
                ><button
                  class="text-button"
                  :disabled="!!busy"
                  @click="selectFiling(filing, true)"
                >
                  분석에 사용 <Sparkles :size="13" />
                </button>
                <button
                  v-if="store.filings.some((f) => f.id === filing.id)"
                  class="text-button"
                  @click="remove(filing)"
                >
                  등록 해제
                </button>
              </div>
            </div>
          </article>
          <div ref="sentinel" class="loading-state" role="status">
            <span v-if="loading">공시를 불러오는 중입니다.</span
            ><button v-else-if="hasMore" class="text-button" @click="load()">더 보기</button>
          </div>
          <EmptyState
            v-if="!loading && !companyFilings.length"
            title="등록된 공시가 없습니다"
            message="새 공시가 등록되면 이곳에 표시됩니다."
          />
        </template>
        <template v-else-if="tab === 'memos'">
          <div class="list-heading">
            <h2>기존 기업분석 메모</h2>
            <label class="sr-only" for="company-memo-search">메모 검색</label>
            <input
              id="company-memo-search"
              v-model="memoSearch"
              type="search"
              class="compact-search"
              placeholder="이 종목의 메모 검색"
            />
          </div>
          <article v-for="memo in filteredMemos" :key="memo.id" class="document-row">
            <span class="document-icon"><StickyNote :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">사내 메모</span
                ><span
                  v-if="store.unread({ kind: 'memo', id: memo.id, version: memo.currentVersion })"
                  class="new-dot"
                  >NEW</span
                >
              </div>
              <button class="document-title" @click="store.openMemo(memo.id)">
                {{ memo.title }}
              </button>
              <p class="small muted">
                {{ date(memo.updatedAt) }} , v{{ memo.currentVersion }} ,
                {{ memo.versions.length }}개 버전
              </p>
              <button class="text-button" @click="store.openMemo(memo.id)">
                본문,버전 확인 <ArrowUpRight :size="13" />
              </button>
              <button class="text-button" :aria-label="`${memo.title} 삭제`" @click="deleteMemo(memo.id,memo.title)"><Trash2 :size="13" />삭제</button>
            </div>
          </article>
          <EmptyState
            v-if="!filteredMemos.length"
            title="표시할 메모가 없습니다"
            message="검색 조건을 바꾸거나 이 종목의 기준 메모를 추가하세요."
          />
        </template>
        <CompanyAnalysisHistory
          v-else-if="tab === 'history'"
          :key="company.id"
          :company-id="company.id"
        />
        <template v-else>
          <div class="list-heading">
            <h2>저장된 분석 보고서</h2>
            <span class="small muted">서버에 저장된 분석 결과</span>
          </div>
          <article v-for="report in companyReports" :key="report.id" class="document-row">
            <span class="document-icon mint"><Sparkles :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">AI 보고서</span
                ><span
                  v-if="store.unread({ kind: 'report', id: report.id, version: report.version })"
                  class="new-dot"
                  >NEW</span
                >
              </div>
              <RouterLink class="document-title" :to="`/analyses/${report.taskId}`">{{
                report.title
              }}</RouterLink>
              <p class="small muted">{{ date(report.savedAt) }} , 원본 메모 보존</p>
              <RouterLink class="text-button" :to="`/analyses/${report.taskId}`"
                >결과 확인 <ArrowUpRight :size="13"
              /></RouterLink>
            </div>
          </article>
          <EmptyState
            v-if="!companyReports.length"
            title="저장된 보고서가 없습니다"
            message="공시와 메모를 선택해 첫 분석을 시작하세요."
          />
        </template>
      </section>
      <aside class="company-tools" :aria-label="tab === 'memos' ? '메모 추가' : '분석 도구'">
        <MemoUpload
          v-if="tab === 'memos'"
          :key="`upload-${company.id}`"
          :company-id="company.id"
          :company-name="company.name"
        />
        <AnalysisLauncher
          v-else
          :key="company.id"
          :company-id="company.id"
          :preferred-filing="preferredFiling"
        />
      </aside>
    </div>
  </section>
  <EmptyState v-else title="기업을 찾을 수 없습니다" message="기업 목록에서 다시 선택해 주세요."
    ><RouterLink to="/companies" class="button secondary">기업 목록</RouterLink></EmptyState
  >
</template>
