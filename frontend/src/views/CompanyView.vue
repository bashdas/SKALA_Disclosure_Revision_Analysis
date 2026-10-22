<script setup lang="ts">
import { notifyError } from '../lib/notifications'
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  FileText,
  StickyNote,
  Sparkles,
  ArrowUpRight,
  Check,
  Trash2,
  Search,
} from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date, disclosureUrl } from '../lib/format'
import { request } from '../services/http'
import { koreaDate, searchDisclosures, type DisclosureRow } from '../services/catalog'
import type { Filing } from '../types/domain'
import UiDatePicker from '../components/UiDatePicker.vue'
import CompanyMarketOverview from '../components/CompanyMarketOverview.vue'
import SkeletonState from '../components/SkeletonState.vue'
import AnalysisLauncher from '../components/AnalysisLauncher.vue'
import EmptyState from '../components/EmptyState.vue'
import MemoUpload from '../components/MemoUpload.vue'
import CompanyAnalysisHistory from '../components/CompanyAnalysisHistory.vue'
const store = useWorkspace(),
  route = useRoute(),
  selectedFiling = ref<Filing | null>(null),
  memoSearch = ref('')
const company = computed(() => store.companies.find((c) => c.id === route.params.companyId))
const tab = computed(() => {
  const requested = String(route.query.tab)
  if (requested === 'history') return 'reports'
  return ['filings', 'memos', 'reports'].includes(requested) ? requested : 'filings'
})
const totalFilings = ref<number | null>(null)
const rows = ref<DisclosureRow[]>([]),
  loading = ref(false),
  error = ref(''),
  hasMore = ref(true),
  page = ref(1),
  search = ref(''),
  busy = ref('')
const start = ref(''),
  end = ref('')
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
    totalFilings.value = null
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
    totalFilings.value = result.total_count
    hasMore.value = result.has_more
    page.value = result.next_page ?? page.value + 1
  } catch (e) {
    notifyError(e)
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
async function deleteMemo(id: string, title: string) {
  if (!window.confirm(`‘${title}’ 메모를 삭제할까요? 기존 분석의 기준 원문은 보존됩니다.`)) return
  try {
    await store.deleteMemo(id)
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '메모 삭제 실패'
  }
}
watch(
  () => route.params.companyId,
  () => {
    selectedFiling.value = null
    store.visitCompany(String(route.params.companyId))
    start.value = end.value = ''
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
const companyMemos = computed(() => store.memosForCompany(String(route.params.companyId)))
const filteredMemos = computed(() =>
  companyMemos.value.filter((m) => m.title.includes(memoSearch.value)),
)
const companyTasks = computed(() => store.tasks.filter((t) => t.companyId === company.value?.id))
const tabs = computed(() => [
  { id: 'filings', name: '공시', icon: FileText, count: totalFilings.value },
  { id: 'memos', name: '메모 관리', icon: StickyNote, count: companyMemos.value.length },
  { id: 'reports', name: 'AI 보고서', icon: Sparkles, count: companyTasks.value.length },
])
</script>
<template>
  <section v-if="company" class="company-workspace" aria-labelledby="company-title">
    <header class="company-workspace-header">
      <CompanyMarketOverview :key="company.id" :company="company" />
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
    <p v-if="error && tab !== 'filings'" class="inline-warning" role="alert">{{ error }}</p>
    <div class="detail-layout without-tools">
      <section class="document-section" aria-label="기업 자료">
        <template v-if="tab === 'filings'">
          <div class="list-heading filing-heading">
            <h2>공시 업데이트</h2>
          </div>
          <form class="filing-filters" aria-label="공시 검색 필터" @submit.prevent="load(true)">
            <label class="filing-search" for="filing-search">
              <span>공시 검색</span>
              <span class="filing-search-control">
                <Search :size="16" aria-hidden="true" />
                <input
                  id="filing-search"
                  v-model="search"
                  type="search"
                  placeholder="공시명으로 검색"
                  maxlength="100"
                />
              </span>
            </label>
            <label
              ><span>시작일</span><UiDatePicker v-model="start" :max="end" label="시작일"
            /></label>
            <label
              ><span>종료일</span
              ><UiDatePicker v-model="end" :min="start" :max="koreaDate()" label="종료일"
            /></label>
            <button class="button secondary" type="submit" :disabled="loading">검색</button>
          </form>
          <p v-if="error" class="inline-warning" role="alert">{{ error }}</p>
          <SkeletonState v-if="loading && !companyFilings.length" :rows="5" />
          <article v-for="filing in companyFilings" :key="filing.id" class="document-row">
            <span class="document-icon"><FileText :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span
                  class="tag"
                  :class="filing.isCorrection ? 'filing-tag-correction' : 'filing-tag-new'"
                  >{{ filing.filingType }}</span
                >
                <span class="small muted filing-date">{{ date(filing.filedAt) }}</span>
                <span class="small muted filing-receipt">{{
                  filing.receiptNo ?? '접수번호 미확인'
                }}</span>
                <span
                  v-if="
                    !store.unread({ kind: 'filing', id: filing.id, version: filing.currentVersion })
                  "
                  class="read-label"
                  ><Check :size="12" /> 확인함</span
                >
              </div>
              <a
                class="document-title"
                :href="disclosureUrl(filing.receiptNo!)"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ filing.title }}
              </a>
            </div>
            <div class="document-actions">
              <button
                v-if="filing.isCorrection"
                class="text-button"
                :disabled="!!busy"
                :data-analysis-receipt="filing.receiptNo"
                @click="selectedFiling = filing"
              >
                분석하기 <Sparkles :size="13" />
              </button>
            </div>
          </article>
          <div ref="sentinel" class="loading-state" role="status">
            <SkeletonState v-if="loading && companyFilings.length" :rows="2" />
            <button v-if="!loading && hasMore" class="text-button" @click="load()">더 보기</button>
          </div>
          <EmptyState
            v-if="!loading && !companyFilings.length"
            title="조회된 공시가 없습니다"
            message="검색 조건이나 조회 기간을 확인해 주세요."
          />
        </template>
        <template v-else-if="tab === 'memos'">
          <div class="list-heading">
            <h2>기존 기업분석 메모</h2>
            <div class="memo-heading-actions">
              <label class="sr-only" for="company-memo-search">메모 검색</label>
              <input
                id="company-memo-search"
                v-model="memoSearch"
                type="search"
                class="compact-search"
                placeholder="이 종목의 메모 검색"
              />
              <MemoUpload :key="company.id" :company-id="company.id" :company-name="company.name" />
            </div>
          </div>
          <article v-for="memo in filteredMemos" :key="memo.id" class="document-row">
            <span class="document-icon"><StickyNote :size="20" /></span>
            <div class="document-info">
              <button class="document-title" @click="store.openMemo(memo.id)">
                {{ memo.title }}
              </button>
              <p class="small muted">
                {{ date(memo.updatedAt) }} , v{{ memo.currentVersion }} ,
                {{ memo.versions.length }}개 버전
              </p>
            </div>
            <div class="document-actions">
              <button class="text-button" @click="store.openMemo(memo.id)">
                본문,버전 확인 <ArrowUpRight :size="13" />
              </button>
              <button
                class="text-button"
                :aria-label="`${memo.title} 삭제`"
                @click="deleteMemo(memo.id, memo.title)"
              >
                <Trash2 :size="13" />삭제
              </button>
            </div>
          </article>
          <EmptyState
            v-if="!filteredMemos.length"
            title="표시할 메모가 없습니다"
            message="검색 조건을 바꾸거나 이 종목의 기준 메모를 추가하세요."
          />
        </template>
        <CompanyAnalysisHistory v-else :key="company.id" :company-id="company.id" />
      </section>
    </div>
    <AnalysisLauncher
      :key="company.id"
      :company-id="company.id"
      :filing="selectedFiling"
      @close="selectedFiling = null"
    />
  </section>
  <SkeletonState v-else-if="loading" variant="company" :rows="5" />
  <EmptyState v-else title="기업을 찾을 수 없습니다" message="기업 목록에서 다시 선택해 주세요."
    ><RouterLink to="/companies" class="button secondary">기업 목록</RouterLink></EmptyState
  >
</template>
