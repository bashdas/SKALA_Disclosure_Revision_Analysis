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
        <div>
          <dt>시가</dt>
          <dd>{{ money(quote?.openPrice) }}</dd>
        </div>
        <div>
          <dt>고가</dt>
          <dd class="up">{{ money(quote?.highPrice) }}</dd>
        </div>
        <div>
          <dt>저가</dt>
          <dd class="down">{{ money(quote?.lowPrice) }}</dd>
        </div>
      </dl>
      <SkeletonState v-if="loading" variant="stats" />
      <template v-else>
        <dl class="company-market-stats">
          <div>
            <dt>거래대금</dt>
            <dd>{{ amount(quote?.tradingValue) }}</dd>
          </div>
          <div>
            <dt>1개월 최고 종가</dt>
            <dd>{{ series.length ? money(Math.max(...series)) : '자료 없음' }}</dd>
          </div>
          <div>
            <dt>거래량</dt>
            <dd>
              {{ quote?.volume == null ? '자료 없음' : formatter.format(quote.volume) + '주' }}
            </dd>
          </div>
        </dl>
        <dl class="company-market-stats">
          <div>
            <dt>시가총액</dt>
            <dd>{{ amount(quote?.marketCap) }}</dd>
          </div>
          <div>
            <dt>1개월 최저 종가</dt>
            <dd>{{ series.length ? money(Math.min(...series)) : '자료 없음' }}</dd>
          </div>
          <div class="company-sector-row">
            <dt>산업군</dt>
            <dd :title="sector || company.sector || '분류 없음'">
              {{ sector || company.sector || '분류 없음' }}
            </dd>
          </div>
        </dl>
      </template>
    </div>
  </div>
</template>
<style scoped>
.company-market {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.company-market-identity {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  min-width: 0;
}
.company-market-name {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.company-market-name > div {
  min-width: 0;
}
.company-market-name .company-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
}
.company-market-name h1 {
  font-size: 22px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.company-market-name p {
  margin-bottom: 3px;
  font-size: 11px;
  line-height: 16px;
  font-variant-numeric: tabular-nums;
}
.company-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.company-name-row :deep(.favorite-button) {
  width: 28px;
  height: 28px;
}
.company-current-price {
  min-width: 0;
  flex-shrink: 0;
  text-align: right;
}
.company-market-price {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 8px;
  font-variant-numeric: tabular-nums;
}
.company-market-price strong {
  font-size: 30px;
  line-height: 1.2;
  letter-spacing: -0.035em;
  font-weight: 650;
  color: var(--ink);
  white-space: nowrap;
}
.company-market-price span {
  font-size: 13px;
  line-height: 18px;
  font-weight: 600;
  white-space: nowrap;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.company-market-panel {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
  min-width: 0;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.company-market-panel > * {
  min-width: 0;
  padding-inline: 18px;
}
.company-market-panel > :first-child {
  padding-left: 0;
}
.company-market-panel > :last-child {
  padding-right: 0;
}
.company-market-panel > :not(:first-child) {
  border-left: 1px solid var(--line);
}
.company-price-chart {
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.company-price-chart :deep(.market-sparkline),
.company-price-chart :deep(.sk-chart-area) {
  width: 100%;
  height: 88px;
}
.company-price-chart :deep(.market-chart-empty) {
  display: grid;
  place-items: center;
  height: 88px;
  font-size: 11px;
}
.company-chart-dates {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  color: var(--muted);
  font-size: 9px;
  line-height: 12px;
  font-variant-numeric: tabular-nums;
}
.company-day-prices,
.company-market-stats {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  margin: 0;
}
.company-day-prices > div,
.company-market-stats > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.company-day-prices dt,
.company-market-stats dt {
  color: var(--muted);
  font-size: 11px;
  line-height: 16px;
  word-break: keep-all;
}
.company-day-prices dd,
.company-market-stats dd {
  margin: 0;
  font-size: 13px;
  line-height: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}
.company-market-stats dd {
  color: var(--ink);
}
.company-market-stats .company-sector-row {
  grid-template-columns: max-content minmax(0, 1fr);
}
.company-sector-row dd {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.company-market-panel > .skeleton-stats {
  grid-column: 2 / -1;
}
@media (max-width: 900px) {
  .company-market {
    gap: 12px;
  }
  .company-market-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    row-gap: 10px;
  }
  .company-market-panel > :nth-child(3) {
    padding-left: 0;
    border-left: 0;
  }
  .company-market-panel > :nth-child(even) {
    padding-right: 0;
  }
  .company-day-prices,
  .company-market-stats {
    gap: 8px;
  }
}
@media (max-width: 650px) {
  .company-market {
    gap: 12px;
  }
  .company-market-identity {
    gap: 12px;
  }
  .company-market-name {
    gap: 10px;
  }
  .company-market-name .company-logo {
    width: 36px;
    height: 36px;
    border-radius: 10px;
  }
  .company-market-name h1 {
    font-size: 18px;
  }
  .company-name-row {
    gap: 4px;
  }
  .company-market-price {
    flex-direction: column;
    align-items: flex-end;
    gap: 0;
  }
  .company-market-price strong {
    font-size: 24px;
  }
  .company-market-price span {
    font-size: 12px;
    line-height: 16px;
  }
  .company-market-panel {
    padding-top: 12px;
    row-gap: 12px;
  }
  .company-market-panel > * {
    padding-inline: 10px;
  }
  .company-market-panel > :nth-child(odd) {
    padding-left: 0;
  }
  .company-market-panel > :nth-child(even) {
    padding-right: 0;
  }
  .company-day-prices > div,
  .company-market-stats > div {
    gap: 6px;
  }
  .company-day-prices dt,
  .company-market-stats dt {
    font-size: 10px;
    line-height: 14px;
  }
  .company-day-prices dd,
  .company-market-stats dd {
    font-size: 12px;
    line-height: 18px;
  }
  .company-price-chart :deep(.market-sparkline),
  .company-price-chart :deep(.market-chart-empty),
  .company-price-chart :deep(.sk-chart-area) {
    height: 72px;
  }
}
</style>
