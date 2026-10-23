<script setup lang="ts">
import { perspectiveLabels, type Evidence, type Perspective, type ReviewReport } from '../types/domain'
import type { MarkdownRange } from '../lib/markdown'
import AnalysisPerspectives from './AnalysisPerspectives.vue'
import MarkdownReport from './MarkdownReport.vue'

defineProps<{
  report: ReviewReport
  perspectives: Perspective[]
  ranges: MarkdownRange[]
  results: Perspective[]
}>()
const emit = defineEmits<{ openEvidence: [source: Evidence] }>()
</script>

<template>
  <section class="report-analysis" aria-labelledby="perspective-analysis-title">
    <h2 id="perspective-analysis-title">관점별 분석</h2>
    <AnalysisPerspectives
      :perspectives="perspectives"
      :decisions="report.perspectiveDecisions"
      :reason="report.noAdditionalAnalysisReason"
      :show-result="false"
      :show-heading="false"
    />
    <div v-if="ranges.length || results.length" class="perspective-analysis-body">
      <MarkdownReport
        v-for="(range, i) in ranges"
        :key="i"
        :content="report.content"
        :range="range"
        :evidence="report.evidence"
        @open-evidence="emit('openEvidence', $event)"
      />
      <article v-for="perspective in results" :key="perspective.type" class="fallback-analysis">
        <h3>{{ perspectiveLabels[perspective.type] }}</h3>
        <p>{{ perspective.result }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.report-analysis {
  margin-top: 32px;
  min-width: 0;
}
.report-analysis > h2 {
  margin: 0 0 18px;
  font-size: 21px;
  line-height: 1.5;
}
.perspective-analysis-body {
  margin-top: 24px;
}
.fallback-analysis + .fallback-analysis {
  margin-top: 24px;
}
.fallback-analysis h3 {
  margin: 0 0 12px;
  font-size: 17px;
}
.fallback-analysis p {
  margin: 0;
  line-height: 1.85;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
