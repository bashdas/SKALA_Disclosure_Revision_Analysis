<script setup lang="ts">
import { computed } from 'vue'
import { Building2, Calculator, ShieldCheck } from 'lucide-vue-next'
import { perspectiveLabels, perspectiveStatusLabels, type Perspective } from '../types/domain'

const props = withDefaults(
  defineProps<{
    perspectives: Perspective[]
    reason?: string | null
    showHeading?: boolean
    showResult?: boolean
  }>(),
  { showHeading: true, showResult: true },
)
const selected = computed(() => props.perspectives.filter((p) => p.selected))
const icons = { INDUSTRY_CONTRACT: Building2, FINANCE: Calculator, FX_HEDGE: ShieldCheck }
</script>

<template>
  <section class="analysis-perspectives" aria-label="선택한 분석 관점">
    <h3 v-if="showHeading" class="perspectives-title">선택한 분석 관점</h3>
    <div v-if="selected.length" class="perspective-grid">
      <article v-for="p in selected" :key="p.type" class="perspective-card">
        <div class="perspective-header">
          <component :is="icons[p.type] ?? ShieldCheck" :size="18" />
          <h4>{{ perspectiveLabels[p.type] ?? p.type }}</h4>
          <span
            class="tag"
            :class="{
              warning: ['INSUFFICIENT_EVIDENCE', 'LIMIT_REACHED', 'FAILED'].includes(p.status),
            }"
          >
            {{ perspectiveStatusLabels[p.status] ?? p.status }}
          </span>
        </div>
        <p>{{ p.selectionReason }}</p>
        <p v-if="showResult && p.result" class="perspective-result">{{ p.result }}</p>
      </article>
    </div>
    <p v-else class="small muted">{{ reason || '선택된 추가 분석 관점이 없습니다.' }}</p>
  </section>
</template>

<style scoped>
.perspectives-title {
  margin: 0 0 16px;
  font-size: 16px;
}
.perspective-header h4 {
  font-size: 13px;
  color: var(--secondary);
}
</style>
