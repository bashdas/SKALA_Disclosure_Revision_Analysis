<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowUpRight, ArrowDownRight } from 'lucide-vue-next'

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
const selected = ref<string>('all'),
  rail = ref<HTMLElement | null>(null)
const filtered = computed(() =>
  market.filter((item) => selected.value === 'all' || item.group === selected.value),
)
function onWheel(event: WheelEvent) {
  const element = rail.value
  if (!element || event.ctrlKey) return // Preserve browser zoom/pinch gestures.
  const rawDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? element.clientWidth : 1
  const next = Math.max(
    0,
    Math.min(element.scrollWidth - element.clientWidth, element.scrollLeft + rawDelta * unit),
  )
  if (next === element.scrollLeft) return // Let the page scroll when the strip reaches an edge.
  event.preventDefault()
  element.scrollLeft = next
}
watch(selected, () => {
  rail.value?.scrollTo({ left: 0 })
})
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
      <span class="market-sample">UI 예시</span>
    </div>
    <div
      ref="rail"
      class="market-rail"
      tabindex="0"
      aria-label="시장 지표 가로 목록"
      @wheel="onWheel"
    >
      <article v-for="item in filtered" :key="item.name" class="market-item">
        <div class="market-label">
          <h2>{{ item.name }}</h2>
          <span>{{ item.unit }}</span>
        </div>
        <div class="market-quote">
          <strong>{{ item.value }}</strong
          ><span class="market-delta" :class="item.up ? 'up' : 'down'"
            ><component :is="item.up ? ArrowUpRight : ArrowDownRight" :size="11" />{{
              item.change
            }}</span
          >
        </div>
      </article>
    </div>
    <p class="market-footnote">표시값은 시세 연동 전 예시 데이터입니다.</p>
  </section>
</template>
<style scoped>
.market-strip {
  margin-bottom: 24px;
  min-width: 0;
}
.market-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 7px;
}
.market-filters {
  display: flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  flex-wrap: wrap;
}
.market-filters button {
  font-size: 11px;
  color: #8290a0;
  padding: 4px 9px;
  border-radius: 4px;
  white-space: nowrap;
}
.market-filters button.selected {
  background: #e8eef5;
  color: #2c4b68;
  font-weight: 650;
}
.market-filters button:hover {
  background: #edf2f7;
}
.market-sample {
  font-size: 9px;
  letter-spacing: 0.4px;
  color: #98a4b2;
  margin-right: 0;
}
.market-rail {
  display: flex;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  background: #fff;
  border: 1px solid #e0e6ee;
  border-radius: 7px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.market-rail::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
.market-item {
  flex: 0 0 185px;
  padding: 11px 15px 10px;
  border-right: 1px solid #edf0f4;
  min-width: 0;
}
.market-item:last-child {
  border-right: 0;
}
.market-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}
.market-label h2 {
  font-size: 10px;
  font-weight: 600;
  color: #6e8093;
  letter-spacing: 0.15px;
  white-space: nowrap;
}
.market-label > span {
  font-size: 8px;
  color: #abb4bf;
  letter-spacing: 0.2px;
}
.market-quote {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
}
.market-quote strong {
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.4px;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.market-delta {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  font-size: 9px;
  font-weight: 550;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.market-delta.up {
  color: #b45353;
}
.market-delta.down {
  color: #4e78aa;
}
.market-footnote {
  text-align: right;
  font-size: 9px;
  color: #a0aab7;
  margin-top: 4px;
}
@media (max-width: 650px) {
  .market-toolbar {
    gap: 7px;
    align-items: flex-start;
  }
  .market-filters {
    gap: 2px;
  }
  .market-filters button {
    font-size: 10px;
    padding: 4px 7px;
  }
  .market-sample {
    display: none;
  }
  .market-item {
    flex-basis: 170px;
    padding: 10px 12px;
  }
  .market-quote strong {
    font-size: 16px;
  }
  .market-footnote {
    text-align: left;
  }
}
</style>
