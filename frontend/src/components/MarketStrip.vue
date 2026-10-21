<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const groups = [
  { id: 'all', label: '전체' },
  { id: 'domestic', label: '국내 지수' },
  { id: 'global', label: '해외 지수' },
  { id: 'fx-rates', label: '환율, 금리' },
  { id: 'commodities', label: '원자재' },
]
const quotes = [
  ['KOSPI', '코스피', 'domestic', 'pt'],
  ['KOSDAQ', '코스닥', 'domestic', 'pt'],
  ['KOSPI 200', '코스피 200', 'domestic', 'pt'],
  ['S&P 500', 'S&P 500', 'global', 'pt'],
  ['NASDAQ', '나스닥', 'global', 'pt'],
  ['NIKKEI 225', '닛케이 225', 'global', 'pt'],
  ['USD/KRW', '달러 환율', 'fx-rates', 'KRW'],
  ['DXY', 'DXY', 'fx-rates', 'pt'],
  ['미국채 10Y', '미국채 10년', 'fx-rates', '금리'],
  ['WTI', 'WTI', 'commodities', 'USD/bbl'],
  ['GOLD', '금', 'commodities', 'USD/oz'],
  ['COPPER', '구리', 'commodities', 'USD/t'],
].map(([name, label, group, unit]) => ({
  name: name!,
  label: label!,
  group: group!,
  unit: unit!,
  value: '미제공',
  change: '',
  up: false,
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
        <article v-if="featured" class="market-item market-featured">
          <div class="market-label">
            <h2 :aria-label="featured.name">{{ featured.label }}</h2>
            <span>{{ featured.unit }}</span>
          </div>
          <div class="market-quote">
            <strong>{{ featured.value }}</strong
            ><span class="market-delta">{{ featured.change }}</span>
          </div>
          <div class="market-sparkline" aria-label="시계열 데이터 미제공"></div>
        </article>
        <div class="market-grid">
          <article v-for="item in secondary" :key="item.name" class="market-item market-small">
            <div class="market-sparkline" aria-label="시계열 데이터 미제공"></div>
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
