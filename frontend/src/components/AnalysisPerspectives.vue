<script setup lang="ts">
import { computed } from 'vue'
import { Check, Minus, CircleHelp } from 'lucide-vue-next'
import { perspectiveLabels, type Perspective } from '../types/domain'

const props = withDefaults(
  defineProps<{
    perspectives: Perspective[]
    decisions?: { type: Perspective['type']; selected: boolean; reason: string }[]
    reason?: string | null
    showHeading?: boolean
    showResult?: boolean
  }>(),
  { showHeading: true, showResult: true },
)
const decisions = computed(
  () =>
    props.decisions ??
    props.perspectives.map((p) => ({
      type: p.type,
      selected: p.selected,
      reason: p.selectionReason,
    })),
)
const cards = computed(() =>
  (['INDUSTRY_CONTRACT', 'FINANCE', 'FX_HEDGE', 'MARKET_NEWS'] as const).map((type) => {
    const decision = decisions.value.find((d) => d.type === type)
    return {
      type,
      state: !decision ? 'undecided' : decision.selected ? 'selected' : 'unselected',
      label: !decision ? '판단 기록 없음' : decision.selected ? '선택' : '미선택',
      reason: decision?.reason || '이 관점의 판단 이유가 저장되지 않았습니다.',
      result: props.perspectives.find((p) => p.type === type)?.result,
    }
  }),
)
</script>

<template>
  <section class="analysis-perspectives" aria-label="선택한 분석 관점">
    <h3 v-if="showHeading" class="perspectives-title">관점 선택과 이유</h3>
    <div class="perspective-grid">
      <article v-for="card in cards" :key="card.type" class="perspective-card" :class="card.state">
        <h4>{{ perspectiveLabels[card.type] }}</h4>
        <span class="tag perspective-selection">
          <Check v-if="card.state === 'selected'" :size="13" aria-hidden="true" />
          <Minus v-else-if="card.state === 'unselected'" :size="13" aria-hidden="true" />
          <CircleHelp v-else :size="13" aria-hidden="true" />
          {{ card.label }}
        </span>
        <p v-if="showResult && card.result" class="perspective-result">{{ card.result }}</p>
        <p>{{ card.reason }}</p>
      </article>
    </div>
    <p v-if="!decisions.length" class="small muted">
      {{ reason || '선택된 추가 분석 관점이 없습니다.' }}
    </p>
  </section>
</template>

<style scoped>
.perspective-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.perspectives-title {
  margin: 0 0 16px;
  font-size: 16px;
}
.perspective-card.selected {
  background: var(--primary-soft);
  border-color: color-mix(in srgb, var(--primary) 40%, var(--line));
}
.perspective-card.unselected {
  background: var(--surface);
  border-style: dashed;
}
.perspective-card.undecided {
  background: var(--card);
  border-style: dotted;
}
.perspective-selection {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: var(--secondary);
  background: var(--surface-strong);
}
.selected .perspective-selection {
  color: var(--on-primary);
  background: var(--primary);
}
.undecided .perspective-selection {
  color: var(--muted);
  background: var(--surface);
}
.perspective-header h4 {
  font-size: 13px;
  color: var(--secondary);
}
@media (max-width: 900px) {
  .perspective-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 650px) {
  .perspective-grid {
    grid-template-columns: 1fr;
  }
}
</style>
