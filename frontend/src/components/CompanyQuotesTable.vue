<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Star, FileText, Sparkles } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { usePreferences } from '../stores/preferences'
import { getWatchlistQuotes, type WatchlistQuote } from '../services/market'
import type { Company } from '../types/domain'
import { date } from '../lib/format'
import StatusPill from './StatusPill.vue'
const props = withDefaults(defineProps<{ companies: Company[]; directory?: boolean }>(), {
  directory: false,
})
const store = useWorkspace(),
  preferences = usePreferences()
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
onMounted(async () => {
  try {
    quotes.value = await getWatchlistQuotes()
  } catch {
    // Unavailable quotes stay empty; never turn missing market data into zero.
    quotes.value = {}
  }
})
const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 })
function price(value?: number) {
  return value == null ? '—' : `${number.format(value)}원`
}
function amount(value?: number) {
  if (value == null) return '—'
  return value >= 1_000_000_000_000
    ? `${number.format(value / 1_000_000_000_000)}조원`
    : `${number.format(value / 100_000_000)}억원`
}
function change(value?: number) {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}
</script>
<template>
  <div
    v-if="companies.length"
    class="watchlist-table-scroll"
    role="region"
    :aria-label="directory ? '기업 시세 목록' : '관심종목 시세 목록'"
    tabindex="0"
  >
    <table
      class="watchlist-table"
      :class="{ 'company-directory-table': directory }"
      :aria-label="directory ? '기업 목록 시세 예시' : '관심종목 시세 예시'"
    >
      <colgroup>
        <col class="watchlist-favorite-col" />
        <col class="watchlist-name-col" />
        <col />
        <col />
        <col />
        <col />
        <col v-if="directory" class="directory-updates-col" />
        <col class="watchlist-sector-col" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col"><span class="sr-only">관심종목 설정</span></th>
          <th scope="col">종목</th>
          <th scope="col" class="numeric">현재가</th>
          <th scope="col" class="numeric">등락률</th>
          <th scope="col" class="numeric">거래대금</th>
          <th scope="col" class="numeric">시가총액</th>
          <th v-if="directory" scope="col">업데이트</th>
          <th scope="col">산업군</th>
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
          <td>
            <button
              class="favorite-button"
              :class="{ selected: preferences.isFavorite(company.id) }"
              :aria-label="`${company.name} 관심종목 ${preferences.isFavorite(company.id) ? '해제' : '추가'}`"
              :aria-pressed="preferences.isFavorite(company.id)"
              @click="preferences.toggleFavorite(company.id)"
            >
              <Star :size="16" />
            </button>
          </td>
          <th scope="row">
            <div class="watchlist-stock">
              <span v-if="directory" class="company-logo" :class="company.id">{{
                company.initials
              }}</span>
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
                  v-if="directory"
                  class="directory-last-update"
                  :title="
                    companyDetails[company.id]?.latest
                      ? '최근 업데이트 ' + date(companyDetails[company.id]?.latest)
                      : '등록된 자료 없음'
                  "
                >
                  {{
                    companyDetails[company.id]?.latest
                      ? date(companyDetails[company.id]?.latest)
                      : '등록된 자료 없음'
                  }}
                </span>
                <div
                  v-if="
                    !directory &&
                    (store.countUnread(company.id, 'filing') > 0 ||
                      store.countUnread(company.id, 'report') > 0)
                  "
                  class="watchlist-updates"
                >
                  <RouterLink
                    v-if="store.countUnread(company.id, 'filing') > 0"
                    :to="`/companies/${company.id}?tab=filings`"
                    ><FileText :size="11" />공시
                    {{ store.countUnread(company.id, 'filing') }}</RouterLink
                  >
                  <RouterLink
                    v-if="store.countUnread(company.id, 'report') > 0"
                    :to="`/companies/${company.id}?tab=reports`"
                    ><Sparkles :size="11" />AI 보고서
                    {{ store.countUnread(company.id, 'report') }}</RouterLink
                  >
                </div>
              </div>
            </div>
          </th>
          <td class="numeric quote-price">{{ price(quotes[company.id]?.price) }}</td>
          <td class="numeric">
            <span
              class="quote-change"
              :class="{
                up: (quotes[company.id]?.changePercent ?? 0) > 0,
                down: (quotes[company.id]?.changePercent ?? 0) < 0,
              }"
              >{{ change(quotes[company.id]?.changePercent) }}</span
            >
          </td>
          <td class="numeric">{{ amount(quotes[company.id]?.tradingValue) }}</td>
          <td class="numeric">{{ amount(quotes[company.id]?.marketCap) }}</td>
          <td v-if="directory">
            <div class="directory-update-links">
              <RouterLink
                v-for="category in categories"
                :key="category.kind"
                :to="{ path: `/companies/${company.id}`, query: { tab: category.tab } }"
                class="directory-update"
                :class="{ unread: store.countUnread(company.id, category.kind) > 0 }"
                :aria-label="`${company.name} ${category.label} 업데이트 ${store.countUnread(company.id, category.kind)}건`"
                :data-testid="`${company.id}-${category.kind}-badge`"
                >{{ category.label }}
                <span>{{ store.countUnread(company.id, category.kind) }}</span></RouterLink
              >
            </div>
            <StatusPill
              v-if="companyDetails[company.id]?.task"
              :status="companyDetails[company.id]!.task!.status"
            />
          </td>
          <td>
            <span class="watchlist-sector">{{ company.sector }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
