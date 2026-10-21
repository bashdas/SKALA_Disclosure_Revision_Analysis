<script setup lang="ts">
import { computed, useId } from 'vue'
const props = withDefaults(
  defineProps<{ values: number[]; baseline: number; label: string; large?: boolean }>(),
  { large: false },
)
const gradient = `sparkline-${useId()}`
const geometry = computed(() => {
  const values = props.values.filter(Number.isFinite)
  if (!values.length) return null
  const min = Math.min(props.baseline, ...values),
    max = Math.max(props.baseline, ...values)
  const range = max - min || 1
  const y = (value: number) => 62 - ((value - min) / range) * 54
  const points = values.map((value, i) => ({
    x: 4 + (i * 172) / Math.max(1, values.length - 1),
    y: y(value),
  }))
  let line = `M ${points[0]!.x} ${points[0]!.y}`
  // Cubic interpolation keeps the small chart readable without another chart dependency.
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1]!,
      point = points[i]!,
      before = points[Math.max(0, i - 2)]!,
      after = points[Math.min(points.length - 1, i + 1)]!
    line += ` C ${previous.x + (point.x - before.x) / 6} ${previous.y + (point.y - before.y) / 6}, ${point.x - (after.x - previous.x) / 6} ${point.y - (after.y - previous.y) / 6}, ${point.x} ${point.y}`
  }
  const last = points.at(-1)!
  return {
    line,
    fill: `${line} L ${last.x} 70 L ${points[0]!.x} 70 Z`,
    last,
    baseline: y(props.baseline),
  }
})
</script>
<template>
  <svg
    v-if="geometry"
    class="market-sparkline"
    viewBox="0 0 180 72"
    preserveAspectRatio="none"
    role="img"
    :aria-label="label"
  >
    <defs>
      <linearGradient :id="gradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="currentColor" stop-opacity="0.22" />
        <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
      </linearGradient>
    </defs>
    <line x1="0" x2="180" :y1="geometry.baseline" :y2="geometry.baseline" class="chart-baseline" />
    <path :d="geometry.fill" :fill="`url(#${gradient})`" />
    <path
      :d="geometry.line"
      fill="none"
      stroke="currentColor"
      :stroke-width="large ? 2.2 : 2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle
      v-if="large"
      :cx="geometry.last.x"
      :cy="geometry.last.y"
      r="6"
      fill="currentColor"
      opacity="0.12"
    />
    <circle
      :cx="geometry.last.x"
      :cy="geometry.last.y"
      :r="large ? 2.3 : 1.8"
      fill="currentColor"
    />
  </svg>
  <span v-else class="market-chart-empty">추이 자료 없음</span>
</template>
<style scoped>
.market-sparkline {
  display: block;
  overflow: visible;
}
.chart-baseline {
  stroke: var(--muted);
  stroke-opacity: 0.45;
  stroke-width: 0.8;
  stroke-dasharray: 4 4;
}
.market-chart-empty {
  font-size: 12px;
  color: var(--muted);
}
</style>
