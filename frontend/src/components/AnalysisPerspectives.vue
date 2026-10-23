<script setup lang="ts">
import { computed } from 'vue'
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
const decisions = computed(() => props.decisions ?? props.perspectives.map((p) => ({
  type: p.type, selected: p.selected, reason: p.selectionReason,
})))
</script>

<template>
  <section class="analysis-perspectives" aria-label="선택한 분석 관점">
    <h3 v-if="showHeading" class="perspectives-title">관점 선택과 이유</h3>
    <div class="perspective-grid">
      <article v-for="type in (['INDUSTRY_CONTRACT', 'FINANCE', 'FX_HEDGE', 'MARKET_NEWS'] as const)" :key="type" class="perspective-card">
        <h4>{{ perspectiveLabels[type] }}</h4>
        <span class="tag">{{ decisions.find((d) => d.type === type)?.selected === true ? '선택' : decisions.some((d) => d.type === type) ? '미선택' : '판단 기록 없음' }}</span>
        <p v-if="showResult && perspectives.find((p) => p.type === type)?.result" class="perspective-result">{{ perspectives.find((p) => p.type === type)?.result }}</p>
        <p>{{ decisions.find((d) => d.type === type)?.reason || '이 관점의 판단 이유가 저장되지 않았습니다.' }}</p>
      </article>
    </div>
    <p v-if="!decisions.length" class="small muted">{{ reason || '선택된 추가 분석 관점이 없습니다.' }}</p>
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
