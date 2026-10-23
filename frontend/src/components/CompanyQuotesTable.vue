<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useWorkspace } from '../stores/workspace'
import { getCompanyUpdates, type CompanyUpdate } from '../services/catalog'
import { getWatchlistQuotes, type WatchlistQuote } from '../services/market'
import type { Company } from '../types/domain'
import { date } from '../lib/format'
import CompanyFavorite from './CompanyFavorite.vue'
import CompanyLogo from './CompanyLogo.vue'
import StatusPill from './StatusPill.vue'
const props = withDefaults(defineProps<{ companies: Company[]; directory?: boolean }>(), {
  directory: false,
})
const store = useWorkspace()
const updates = ref<Record<string, CompanyUpdate>>({})
let updateGeneration = 0
async function refreshUpdates() {
  const generation = ++updateGeneration
  await getCompanyUpdates(props.companies, (id, value) => {
    if (generation === updateGeneration) updates.value[id] = value
  })
}
watch(() => props.companies.map((c) => c.id + ':' + c.code).join(','), refreshUpdates, {
  immediate: true,
})
const updateTimer = setInterval(refreshUpdates, 300_000)
onUnmounted(() => {
  clearInterval(updateTimer)
  updateGeneration++
})
function updateCount(id: string, kind: 'filing' | 'memo' | 'report') {
  if (kind === 'filing')
    return (
      updates.value[id]?.filingCount ??
      (updates.value[id]?.filingStatus === 'error'
        ? '조회 실패'
        : updates.value[id]
          ? '확인 불가'
          : '조회 중')
    )
  if (kind === 'memo') return store.memosForCompany(id).length
  return store.savedReports.filter(
    (r) => store.tasks.find((t) => t.id === r.taskId)?.companyId === id,
  ).length
}
function latestUpdate(id: string) {
  const latest = [companyDetails.value[id]?.latest, updates.value[id]?.latest]
    .filter(Boolean)
    .sort()
    .at(-1)
  if (latest) return '최근 업데이트 ' + date(latest)
  const update = updates.value[id]
  return !update
    ? '공시 조회 중'
    : update.filingStatus === 'error'
      ? '공시 조회 실패'
      : '최근 90일 공시 없음'
}
const categories = [
  { kind: 'filing', tab: 'filings', label: '공시' },
  { kind: 'memo', tab: 'memos', label: '메모' },
  { kind: 'report', tab: 'reports', label: 'AI 보고서' },
] as const
const companyDetails = computed(() =>
  Object.fromEntries(
    props.companies.map((company) => {
      const latest = [
        ...store.filings.filter((f) => f.companyId === company.id).map((f) => f.filedAt),
        ...store.memos.filter((m) => m.companyName === company.name).map((m) => m.updatedAt),
        ...store.savedReports
          .filter((r) => store.tasks.find((t) => t.id === r.taskId)?.companyId === company.id)
          .map((r) => r.savedAt!),
      ]
        .sort()
        .at(-1)
      const task = store.tasks.find(
        (t) => t.companyId === company.id && ['QUEUED', 'RUNNING', 'SAVING'].includes(t.status),
      )
      return [company.id, { latest, task }]
    }),
  ),
)
const quotes = ref<Record<string, WatchlistQuote>>({})
const quoteError = ref(false)
const quoteLoading = ref(false)
let generation = 0
async function refreshQuotes() {
  const current = ++generation
  quoteLoading.value = true
  quoteError.value = false
  try {
    const result = await getWatchlistQuotes(props.companies)
    if (current === generation) quotes.value = result
  } catch {
    if (current === generation) quoteError.value = true
  } finally {
    if (current === generation) quoteLoading.value = false
  }
}
watch(() => props.companies.map((c) => c.id + ':' + c.code).join(','), refreshQuotes, {
  immediate: true,
})
const refreshTimer = setInterval(refreshQuotes, 60_000)
onUnmounted(() => {
  clearInterval(refreshTimer)
  generation++
})
const missingQuote = computed(() =>
  quoteLoading.value ? '조회 중' : quoteError.value ? '조회 실패' : '시세 없음',
)
const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 })
function price(value?: number | null) {
  return value == null ? missingQuote.value : `${number.format(value)}원`
}
function amount(value?: number | null) {
  if (value == null) return missingQuote.value
  return value >= 1_000_000_000_000
    ? `${number.format(value / 1_000_000_000_000)}조원`
    : `${number.format(value / 100_000_000)}억원`
}
function change(value?: number | null) {
  return value == null ? missingQuote.value : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}
</script>
<template>
  <p v-if="quoteError" class="field-error" role="alert">
    시세 갱신에 실패했습니다. 기존 수신 값이 있으면 유지하며 1분 후 재시도합니다.
  </p>
  <div
    v-if="companies.length"
    class="watchlist-table-scroll"
    role="region"
    :aria-label="directory ? '기업 시세 목록' : '관심종목 시세 목록'"
    tabindex="0"
  >
    <table
      class="watchlist-table company-directory-table"
      :aria-label="directory ? '기업 목록 시세' : '관심종목 시세'"
    >
      <colgroup>
        <col class="watchlist-name-col" />
        <col />
        <col />
        <col />
        <col />
        <col class="directory-updates-col" />
        <col class="watchlist-sector-col" />
        <col class="watchlist-favorite-col" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col">종목</th>
          <th scope="col" class="numeric">현재가</th>
          <th scope="col" class="numeric">등락률</th>
          <th scope="col" class="numeric">거래대금</th>
          <th scope="col" class="numeric">시가총액</th>
          <th scope="col">업데이트</th>
          <th scope="col">산업군</th>
          <th scope="col"><span class="sr-only">관심종목 설정</span></th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="company in companies"
          :key="company.id"
          class="watchlist-row"
          :class="{ 'company-row': directory }"
          :data-testid="`${directory ? 'company' : 'favorite'}-${company.id}`"
        >
          <th scope="row">
            <div class="watchlist-stock">
              <CompanyLogo :code="company.code" :name="company.name" />
              <div class="watchlist-company">
                <div class="watchlist-stock-name">
                  <h2 class="watchlist-stock-title">
                    <RouterLink :to="`/companies/${company.id}`" :title="company.name">{{
                      company.name
                    }}</RouterLink>
                  </h2>
                  <span class="watchlist-code">{{ company.code }}</span>
                </div>
                <span
                  v-if="!updates[company.id]"
                  class="skeleton skeleton-value"
                  aria-label="공시 업데이트 조회 중"
                ></span>
                <span
                  v-else
                  class="directory-last-update"
                  :title="latestUpdate(company.id)"
                >
                  {{ latestUpdate(company.id) }}
                </span>
              </div>
            </div>
          </th>
          <td class="numeric quote-price">
            <span
              v-if="quoteLoading && !quotes[company.id]"
              class="skeleton skeleton-value"
              aria-label="현재가 조회 중"
            ></span
            ><template v-else>{{ price(quotes[company.id]?.price) }}</template>
          </td>
          <td class="numeric">
            <span
              v-if="quoteLoading && !quotes[company.id]"
              class="skeleton skeleton-value"
              aria-label="등락률 조회 중"
            ></span>
            <span
              v-else
              class="quote-change"
              :class="{
                up: (quotes[company.id]?.changePercent ?? 0) > 0,
                down: (quotes[company.id]?.changePercent ?? 0) < 0,
              }"
              >{{ change(quotes[company.id]?.changePercent) }}</span
            >
          </td>
          <td class="numeric">
            <span
              v-if="quoteLoading && !quotes[company.id]"
              class="skeleton skeleton-value"
              aria-label="거래대금 조회 중"
            ></span
            ><template v-else>{{ amount(quotes[company.id]?.tradingValue) }}</template>
          </td>
          <td class="numeric">
            <span
              v-if="quoteLoading && !quotes[company.id]"
              class="skeleton skeleton-value"
              aria-label="시가총액 조회 중"
            ></span
            ><template v-else>{{ amount(quotes[company.id]?.marketCap) }}</template>
          </td>
          <td class="company-updates-cell">
            <div class="directory-update-links">
              <RouterLink
                v-for="category in categories"
                :key="category.kind"
                :to="{ path: `/companies/${company.id}`, query: { tab: category.tab } }"
                class="directory-update"
                :class="{ unread: store.countUnread(company.id, category.kind) > 0 }"
                :aria-label="`${company.name} ${category.label} ${updateCount(company.id, category.kind)}건`"
                :data-testid="`${company.id}-${category.kind}-badge`"
                >{{ category.label }}
                <span
                  v-if="category.kind === 'filing' && !updates[company.id]"
                  class="skeleton skeleton-value"
                  style="width: 24px"
                ></span
                ><span v-else>{{ updateCount(company.id, category.kind) }}</span></RouterLink
              >
            </div>
            <StatusPill
              v-if="companyDetails[company.id]?.task"
              :status="companyDetails[company.id]!.task!.status"
            />
          </td>
          <td class="company-sector-cell">
            <span
              v-if="!updates[company.id]"
              class="skeleton skeleton-value"
              aria-label="산업군 조회 중"
            ></span>
            <span v-else class="watchlist-sector">{{
              updates[company.id]?.sector ||
              company.sector ||
              (!updates[company.id]
                ? '조회 중'
                : updates[company.id]?.sectorStatus === 'error'
                  ? '조회 실패'
                  : '분류 없음')
            }}</span>
          </td>
          <td>
            <CompanyFavorite :company-id="company.id" :name="company.name" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
