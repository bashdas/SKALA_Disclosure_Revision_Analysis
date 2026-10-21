<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import type { Company } from '../types/domain'
import { getWatchlistQuotes, type WatchlistQuote } from '../services/market'
import { request } from '../services/http'
import CompanyFavorite from './CompanyFavorite.vue'
import CompanyLogo from './CompanyLogo.vue'
import MarketSparkline from './MarketSparkline.vue'
import SkeletonState from './SkeletonState.vue'
const props = defineProps<{ company: Company }>()
const quote = ref<WatchlistQuote | null>(null)
const history = ref<{
  series: number[]
  previous_close: number
  start_date: string
  end_date: string
} | null>(null)
const sector = ref(''),
  loading = ref(true),
  error = ref(false)
let generation = 0
async function refresh() {
  const current = ++generation,
    company = props.company
  if (!quote.value) loading.value = true
  if (!/^[0-9]{6}$/.test(company.code)) {
    loading.value = false
    return
  }
  const results = await Promise.allSettled([
    getWatchlistQuotes([company]),
    request<NonNullable<typeof history.value>>('/market/history/' + company.code, {}, false),
    request<{ items: Record<string, { sector: string | null }> }>(
      '/market/sectors?codes=' + company.code,
      {},
      false,
    ),
  ])
  if (current !== generation) return
  const [price, chart, classification] = results
  error.value = price.status === 'rejected' || chart.status === 'rejected'
  if (price.status === 'fulfilled') quote.value = price.value[company.id] ?? null
  if (chart.status === 'fulfilled') history.value = chart.value
  if (classification.status === 'fulfilled')
    sector.value = classification.value.items[company.code]?.sector ?? ''
  loading.value = false
}
watch(
  () => props.company.id + ':' + props.company.code,
  () => {
    quote.value = null
    history.value = null
    sector.value = ''
    error.value = false
    void refresh()
  },
  { immediate: true },
)
const timer = setInterval(refresh, 60_000)
onUnmounted(() => {
  generation++
  clearInterval(timer)
})
const formatter = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 })
const money = (n?: number | null) => (n == null ? '시세 없음' : formatter.format(n) + '원')
function amount(n?: number | null) {
  if (n == null) return '시세 없음'
  return n >= 1e12 ? formatter.format(n / 1e12) + '조원' : formatter.format(n / 1e8) + '억원'
}
const direction = computed(() =>
  (quote.value?.changePercent ?? 0) > 0
    ? 'up'
    : (quote.value?.changePercent ?? 0) < 0
      ? 'down'
      : '',
)
const series = computed(() => history.value?.series ?? [])
const delta = computed(() =>
  quote.value?.changePercent == null
    ? '등락률 없음'
    : (quote.value.changePercent > 0 ? '+' : '') + quote.value.changePercent.toFixed(2) + '%',
)
const chartDate = (value?: string) => (value ? value.slice(4, 6) + '.' + value.slice(6, 8) : '')
</script>

<template>
  <div class="company-market" :aria-busy="loading">
    <div class="company-market-identity">
      <div class="company-market-name">
        <CompanyLogo :code="company.code" :name="company.name" />
        <div>
          <p class="small muted">{{ company.code }}</p>
          <div class="company-name-row">
            <h1 id="company-title">{{ company.name }}</h1>
            <CompanyFavorite :company-id="company.id" :name="company.name" />
          </div>
        </div>
      </div>
      <div class="company-current-price">
        <SkeletonState v-if="loading" variant="price" />
        <div v-else class="company-market-price" :class="direction">
          <strong>{{ money(quote?.price) }}</strong
          ><span>{{ delta }}</span>
        </div>
        <button v-if="error" class="text-button small" @click="refresh">시세 다시 조회</button>
      </div>

    </div>
    <div class="company-market-panel">
      <div class="company-price-chart" :class="direction">
        <SkeletonState v-if="loading" variant="chart" />
        <template v-else>
          <MarketSparkline
            :values="series"
            :baseline="history?.previous_close ?? 0"
            :label="company.name + ' 최근 한 달 일별 주가'"
          />
          <div v-if="series.length" class="company-chart-dates">
            <span>{{ chartDate(history?.start_date) }}</span
            ><span>{{ chartDate(history?.end_date) }}</span>
          </div>
        </template>
      </div>
      <dl v-if="!loading" class="company-day-prices">
        <div><dt>시가</dt><dd>{{ money(quote?.openPrice) }}</dd></div>
        <div><dt>고가</dt><dd class="up">{{ money(quote?.highPrice) }}</dd></div>
        <div><dt>저가</dt><dd class="down">{{ money(quote?.lowPrice) }}</dd></div>
      </dl>
      <SkeletonState v-if="loading" variant="stats" />
      <template v-else>
        <dl class="company-market-stats">
          <div><dt>거래대금</dt><dd>{{ amount(quote?.tradingValue) }}</dd></div>
          <div><dt>1개월 최고 종가</dt><dd>{{ series.length ? money(Math.max(...series)) : '자료 없음' }}</dd></div>
          <div><dt>거래량</dt><dd>{{ quote?.volume == null ? '자료 없음' : formatter.format(quote.volume) + '주' }}</dd></div>
        </dl>
        <dl class="company-market-stats">
          <div><dt>시가총액</dt><dd>{{ amount(quote?.marketCap) }}</dd></div>
          <div><dt>1개월 최저 종가</dt><dd>{{ series.length ? money(Math.min(...series)) : '자료 없음' }}</dd></div>
          <div><dt>산업군</dt><dd>{{ sector || company.sector || '분류 없음' }}</dd></div>
        </dl>
      </template>
    </div>
  </div>
</template>
<style scoped>
.company-market {
  display: grid;
  grid-template-columns: minmax(260px, 0.85fr) minmax(0, 1.4fr);
  align-items: start;
  gap: 48px;
}
.company-name-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.company-market-identity {
  min-width: 0;
}
.company-market-name {
  display: flex;
  gap: 18px;
  align-items: center;
  min-width: 0;
}
.company-market-name .company-logo {
  width: 64px;
  height: 64px;
  border-radius: 16px;
}
.company-market-name h1 {
  font-size: clamp(22px, 2.3vw, 30px);
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.company-market-name p {
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}
.company-market-panel {
  min-width: 0;
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 32px;
  align-items: start;
  padding-top: 4px;
}
.company-current-price {
  margin-top: 24px;
  min-width: 0;
}
.company-metric-label {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 8px;
}
.company-market-price {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 10px;
  font-variant-numeric: tabular-nums;
}
.company-market-price strong {
  font-size: 38px;
  letter-spacing: -0.035em;
  font-weight: 650;
  color: var(--ink);
  white-space: nowrap;
}
.company-market-price span {
  font-size: 15px;
  font-weight: 600;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.company-price-chart {
  min-width: 0;
}
.company-chart-heading {
  color: var(--muted);
  font-size: 11px;
  margin-bottom: 9px;
  text-align: right;
}
.company-chart-dates {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  font-size: 10px;
  margin-top: 7px;
  font-variant-numeric: tabular-nums;
}
.company-price-chart :deep(.market-sparkline) {
  width: 100%;
  height: 88px;
}
.company-price-chart :deep(.market-chart-empty) {
  display: grid;
  place-items: center;
  height: 88px;
  font-size: 11px;
}
.company-market-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 26px 28px;
  margin: 0;
}
.company-market-stats > div {
  min-width: 0;
  display: grid;
  gap: 5px;
}
.company-market-stats dt {
  color: var(--muted);
  font-size: 12px;
}
.company-market-stats dd {
  margin: 0;
  color: var(--ink);
  font-size: 17px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.company-market-stats .company-sector-stat {
  grid-column: auto;
}
@media (max-width: 1000px) {
  .company-market {
    grid-template-columns: minmax(0, 1fr);
    gap: 28px;
  }
  .company-market-panel {
    grid-template-columns: 190px minmax(0, 1fr);
  }
}
@media (max-width: 650px) {
  .company-market {
    gap: 24px;
  }
  .company-market-name .company-logo {
    width: 52px;
    height: 52px;
  }
  .company-market-panel {
    grid-template-columns: 130px minmax(0, 1fr);
    gap: 20px;
  }
  .company-market-price strong {
    font-size: 32px;
  }
  .company-current-price {
    margin-top: 20px;
  }
  .company-market-stats {
    gap: 18px 16px;
  }
  .company-market-stats dt {
    font-size: 11px;
  }
  .company-market-stats dd {
    font-size: 14px;
  }
  .company-price-chart :deep(.market-sparkline) {
    height: 72px;
  }
}
.company-day-prices { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 24px 0 0; max-width: 380px; }
.company-day-prices dt { color: var(--muted); font-size: 12px; margin-bottom: 7px; }
.company-day-prices dd { margin: 0; font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }

/* 기업 식별 정보와 가격을 상단에, 차트와 지표를 하단에 묶습니다. */
.company-market { display: flex; flex-direction: column; gap: 32px; }
.company-market-identity { display: flex; justify-content: space-between; align-items: flex-start; gap: 32px; width: 100%; }
.company-current-price { margin: 0; text-align: right; }
.company-market-price { justify-content: flex-end; }
.company-market-panel { width: 100%; grid-template-columns: 190px 204px minmax(0, 1fr); gap: 32px; padding: 28px 0 8px; border-top: 1px solid var(--line); }
.company-day-prices { display: grid; grid-template-columns: 1fr; gap: 16px; max-width: none; margin: 0; padding-left: 24px; padding-right: 28px; border-right: 1px solid var(--line); }
.company-day-prices > div { display: grid; grid-template-columns: 32px auto; gap: 12px; align-items: baseline; }
.company-day-prices dt { margin: 0; }
.company-market-stats { gap: 18px 32px; }
.company-market-stats > div { display: grid; grid-template-columns: 112px auto; justify-content: start; align-items: baseline; gap: 12px; }
.company-market-stats dd { font-size: 15px; text-align: left; }
@media (max-width: 1000px) {
 .company-market-panel { grid-template-columns: 190px minmax(0, 1fr); }
 .company-day-prices { padding-right: 0; border: 0; }
 .company-market-stats, .company-market-panel > .skeleton-stats { grid-column: 1 / -1; }
}
@media (max-width: 650px) {
 .company-market-identity { align-items: flex-start; flex-direction: column; gap: 24px; }
 .company-current-price { text-align: left; }
 .company-market-price { justify-content: flex-start; }
 .company-market-panel { grid-template-columns: 130px minmax(0, 1fr); gap: 24px; padding-top: 24px; }
 .company-market-stats { grid-column: 1 / -1; gap: 18px 24px; }
 .company-market-stats > div { grid-template-columns: 1fr; gap: 6px; }
 .company-market-stats dd { text-align: left; font-size: 15px; }
}

.company-market-panel { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; align-items: stretch; }
.company-market-panel > * { padding-inline: 32px; min-width: 0; }
.company-market-panel > :first-child { padding-left: 0; }
.company-market-panel > :last-child { padding-right: 0; }
.company-market-panel > :not(:first-child) { border-left: 1px solid var(--line); }
.company-day-prices { border-right: 0; }
.company-price-chart :deep(.market-sparkline), .company-chart-dates { width: 100%; max-width: 100%; }
.company-market-stats { grid-template-columns: 1fr; gap: 16px; }
@media(max-width: 1000px) {
 .company-market-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 28px; }
 .company-market-stats { grid-column: auto; }
 .company-market-panel > :nth-child(3) { border-left: 0; padding-left: 0; }
}
@media(max-width: 650px) {
 .company-market-panel > * { padding-inline: 20px; }
 .company-market-panel > :first-child, .company-market-panel > :nth-child(3) { padding-left: 0; }
 .company-market-panel > :nth-child(even) { padding-right: 0; }
 .company-price-chart :deep(.market-sparkline), .company-chart-dates { width: 100%; }
 .company-market-stats > div { grid-template-columns: 1fr; }
}

.company-market-panel > .company-price-chart,
.company-market-panel > .company-day-prices,
.company-market-panel > .company-market-stats { padding-inline: 24px; }
.company-price-chart { display: flex; flex-direction: column; justify-content: center; align-items: flex-start; }
.company-market-panel > .company-price-chart { padding-left: 0; }
.company-price-chart :deep(.market-sparkline), .company-chart-dates { margin-inline: 0; }
.company-day-prices, .company-market-stats { justify-content: center; align-content: center; grid-template-columns: minmax(0, 1fr); }
.company-day-prices > div, .company-market-stats > div { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 12px; width: 100%; }
.company-day-prices dd, .company-market-stats dd { text-align: right; }
.company-market-panel > .company-market-stats:last-child { padding-right: 24px; justify-content: end; }
@media(max-width: 650px) {
 .company-market-panel > .company-price-chart,
 .company-market-panel > .company-day-prices,
 .company-market-panel > .company-market-stats { padding-inline: 12px; }
 .company-market-panel > .company-price-chart { padding-left: 0; }
 .company-market-panel > .company-market-stats:last-child { padding-right: 12px; }
 .company-day-prices > div { grid-template-columns: 28px minmax(0, 1fr); gap: 8px; }
 .company-market-stats > div { grid-template-columns: 1fr; gap: 6px; }
 .company-market-stats dd { text-align: left; }
}
</style>
