<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MarketSparkline from './MarketSparkline.vue'

// All values are fictional UI examples, not historical/current quotes.
const groups = [
  { id: 'all', label: '전체' },
  { id: 'domestic', label: '국내 지수' },
  { id: 'global', label: '해외 지수' },
  { id: 'fx-rates', label: '환율·금리' },
  { id: 'commodities', label: '원자재' },
] as const
const market = [
  { name: 'KOSPI', group: 'domestic', unit: 'pt', value: '2,650.00', change: '+0.42%', up: true },
  { name: 'KOSDAQ', group: 'domestic', unit: 'pt', value: '850.00', change: '−0.28%', up: false },
  { name: 'KOSPI 200', group: 'domestic', unit: 'pt', value: '355.00', change: '+0.36%', up: true },
  { name: 'S&P 500', group: 'global', unit: 'pt', value: '5,300.00', change: '+0.51%', up: true },
  { name: 'NASDAQ', group: 'global', unit: 'pt', value: '17,000.00', change: '+0.74%', up: true },
  {
    name: 'NIKKEI 225',
    group: 'global',
    unit: 'pt',
    value: '39,000.00',
    change: '−0.32%',
    up: false,
  },
  {
    name: 'USD/KRW',
    group: 'fx-rates',
    unit: 'KRW',
    value: '1,350.00',
    change: '+0.15%',
    up: true,
  },
  { name: 'DXY', group: 'fx-rates', unit: 'pt', value: '103.50', change: '−0.12%', up: false },
  {
    name: '미국채 10Y',
    group: 'fx-rates',
    unit: '금리',
    value: '4.25%',
    change: '+3.0bp',
    up: true,
  },
  {
    name: 'WTI',
    group: 'commodities',
    unit: 'USD/bbl',
    value: '78.50',
    change: '+0.80%',
    up: true,
  },
  {
    name: 'GOLD',
    group: 'commodities',
    unit: 'USD/oz',
    value: '2,350.00',
    change: '+0.25%',
    up: true,
  },
  {
    name: 'COPPER',
    group: 'commodities',
    unit: 'USD/t',
    value: '9,500.00',
    change: '−0.45%',
    up: false,
  },
]

// Normalized, deterministic illustrative paths; these are not intraday observations.
const profiles = [
  [100, 100.08, 100.21, 100.45, 100.74, 100.88, 100.77, 100.55, 100.32, 100.27, 100.35, 100.42],
  [100, 100.24, 100.18, 99.92, 99.83, 99.91, 99.78, 99.86, 99.74, 99.69, 99.77, 99.72],
  [100, 100.04, 100.12, 100.08, 100.26, 100.34, 100.28, 100.39, 100.32, 100.28, 100.41, 100.36],
  [100, 100.14, 100.48, 100.67, 100.55, 100.73, 100.62, 100.56, 100.64, 100.51, 100.58, 100.51],
  [100, 100.26, 100.65, 100.96, 100.85, 101.04, 100.89, 100.96, 100.81, 100.88, 100.79, 100.74],
  [100, 100.21, 100.14, 99.92, 99.81, 99.95, 99.86, 99.75, 99.83, 99.69, 99.73, 99.68],
  [100, 100.06, 100.12, 100.09, 100.18, 100.14, 100.22, 100.17, 100.12, 100.19, 100.13, 100.15],
  [100, 100.11, 100.23, 100.18, 100.06, 99.99, 100.07, 99.94, 99.99, 99.92, 99.95, 99.88],
  [100, 100.08, 100.04, 100.16, 100.12, 100.25, 100.21, 100.33, 100.25, 100.29, 100.27, 100.3],
  [100, 100.15, 100.42, 100.33, 100.51, 100.68, 100.57, 100.73, 100.63, 100.82, 100.75, 100.8],
  [100, 100.03, 100.11, 100.06, 100.16, 100.19, 100.13, 100.22, 100.17, 100.28, 100.22, 100.25],
  [100, 99.91, 99.97, 99.79, 99.83, 99.71, 99.76, 99.63, 99.69, 99.57, 99.62, 99.55],
]
const labels: Record<string, string> = {
  KOSPI: '코스피',
  KOSDAQ: '코스닥',
  'KOSPI 200': '코스피 200',
  NASDAQ: '나스닥',
  'NIKKEI 225': '닛케이 225',
  'USD/KRW': '달러 환율',
  '미국채 10Y': '미국채 10년',
  GOLD: '금',
  COPPER: '구리',
}
const quotes = market.map((item, index) => ({
  ...item,
  label: labels[item.name] ?? item.name,
  series: profiles[index]!,
}))
const selected = ref<string>('all'),
  rail = ref<HTMLElement | null>(null)
const filtered = computed(() =>
  quotes.filter((item) => selected.value === 'all' || item.group === selected.value),
)
const featured = computed(() => (selected.value === 'all' ? filtered.value[0] : undefined))
const secondary = computed(() => (featured.value ? filtered.value.slice(1) : filtered.value))
function onWheel(event: WheelEvent) {
  const element = rail.value
  if (!element || event.ctrlKey) return
  const rawDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? element.clientWidth : 1
  const next = Math.max(
    0,
    Math.min(element.scrollWidth - element.clientWidth, element.scrollLeft + rawDelta * unit),
  )
  if (next === element.scrollLeft) return
  event.preventDefault()
  element.scrollLeft = next
}
watch(selected, () => rail.value?.scrollTo({ left: 0 }))
</script>
<template>
  <section class="market-strip" aria-label="시장 지표">
    <div class="market-toolbar">
      <div class="market-filters" role="group" aria-label="시장 지표 분류">
        <button
          v-for="group in groups"
          :key="group.id"
          :aria-pressed="selected === group.id"
          :class="{ selected: selected === group.id }"
          @click="selected = group.id"
        >
          {{ group.label }}
        </button>
      </div>
    </div>
    <div
      ref="rail"
      class="market-rail"
      tabindex="0"
      aria-label="시장 지표 가로 목록"
      @wheel="onWheel"
    >
      <div class="market-board" :class="{ 'has-featured': featured }">
        <article
          v-if="featured"
          class="market-item market-featured"
          :class="featured.up ? 'up' : 'down'"
        >
          <div class="market-label">
            <h2 :aria-label="featured.name">{{ featured.label }}</h2>
            <span>{{ featured.unit }}</span>
          </div>
          <div class="market-quote">
            <strong>{{ featured.value }}</strong
            ><span class="market-delta">{{ featured.change }}</span>
          </div>
          <MarketSparkline
            :values="featured.series"
            :baseline="100"
            :label="`${featured.label} 추이 그래프`"
            large
          />
        </article>
        <div class="market-grid">
          <article
            v-for="item in secondary"
            :key="item.name"
            class="market-item market-small"
            :class="item.up ? 'up' : 'down'"
          >
            <MarketSparkline
              :values="item.series"
              :baseline="100"
              :label="`${item.label} 추이 그래프`"
            />
            <div class="market-copy">
              <div class="market-label">
                <h2 :aria-label="item.name">{{ item.label }}</h2>
                <span>{{ item.unit }}</span>
              </div>
              <div class="market-quote">
                <strong>{{ item.value }}</strong
                ><span class="market-delta">{{ item.change }}</span>
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>
<style scoped>
.market-strip {
  margin-bottom: 28px;
  min-width: 0;
}
.market-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
}
.market-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
}
.market-filters button {
  font-size: 12px;
  color: var(--muted);
  padding: 4px 9px;
  border-radius: 8px;
  white-space: nowrap;
}
.market-filters button.selected {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 650;
}
.market-filters button:hover {
  background: var(--surface-strong);
}
.market-rail {
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.market-rail::-webkit-scrollbar {
  display: none;
}
.market-rail:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 4px;
  border-radius: 6px;
}
.market-board {
  min-width: 900px;
  background: var(--background);
  padding: 12px 0;
}
.market-board.has-featured {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  min-width: 1120px;
}
.market-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  row-gap: 16px;
}
.market-item {
  min-width: 0;
}
.market-item.up {
  color: var(--up);
}
.market-item.down {
  color: var(--down);
}
.market-featured {
  padding: 2px 24px 0 0;
  border-right: 1px solid var(--line);
}
.market-label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
.market-label h2 {
  color: var(--secondary);
  font-size: 14px;
  line-height: 1.4;
  font-weight: 600;
  letter-spacing: -0.02em;
  white-space: nowrap;
}
.market-label > span {
  color: var(--muted);
  font-size: 12px;
}
.market-quote {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 8px;
  font-variant-numeric: tabular-nums;
  line-height: 1.35;
}
.market-quote strong {
  color: var(--ink);
  font-size: 19px;
  font-weight: 550;
  letter-spacing: -0.025em;
  white-space: nowrap;
}
.market-delta {
  font-size: 12px;
  font-weight: 550;
  white-space: nowrap;
}
.market-featured .market-label h2 {
  font-size: 16px;
}
.market-featured .market-quote strong {
  font-size: 26px;
}
.market-featured .market-delta {
  font-size: 14px;
}
.market-featured :deep(.market-sparkline) {
  width: 100%;
  height: 134px;
  margin-top: 18px;
}
.market-small {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  min-height: 44px;
  border-right: 1px solid var(--line);
}
.market-small:nth-child(3n) {
  border-right: 0;
}
.market-small :deep(.market-sparkline) {
  width: 64px;
  height: 42px;
  flex-shrink: 0;
}
.market-copy {
  min-width: 0;
}
@media (max-width: 650px) {
  .market-filters {
    gap: 2px;
  }
  .market-filters button {
    padding: 4px 7px;
  }
  .market-board.has-featured {
    grid-template-columns: 220px minmax(0, 1fr);
    min-width: 1080px;
  }
  .market-featured {
    padding-right: 20px;
  }
  .market-small {
    padding: 0 16px;
  }
  .market-featured .market-quote strong {
    font-size: 24px;
  }
}
</style>
