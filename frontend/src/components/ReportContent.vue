<script setup lang="ts">
import { ArrowRight } from 'lucide-vue-next'
import type { Evidence, ReviewReport } from '../types/domain'
import type { PresentationBlock } from '../lib/report-presentation'
import MarkdownReport from './MarkdownReport.vue'
import MemoRevisionProposals from './MemoRevisionProposals.vue'
import ReviewPoints from './ReviewPoints.vue'

defineProps<{ item: PresentationBlock; report: ReviewReport }>()
const emit = defineEmits<{
  openEvidence: [source: Evidence]
  openMemo: [paragraph: number | null]
}>()
</script>

<template>
  <template v-if="item.block.type === 'markdown' || item.block.type === 'sources'">
    <h3 v-if="item.keepHeading && item.block.heading">{{ item.block.heading }}</h3>
    <MarkdownReport
      :content="report.content"
      :range="
        item.block.type === 'sources' || !item.block.heading
          ? item.block.range
          : { from: item.block.range.from + 3, to: item.block.range.to }
      "
      hide-report-title
      :evidence="report.evidence"
      @open-evidence="emit('openEvidence', $event)"
    />
  </template>
  <MemoRevisionProposals
    v-else-if="item.block.type === 'memo-proposals'"
    :findings="report.findings"
    :evidence="report.evidence"
    heading-tag="h3"
    @open-evidence="emit('openEvidence', $event)"
    @open-memo="emit('openMemo', $event)"
  />
  <ReviewPoints
    v-else-if="item.block.type === 'review-points'"
    :points="report.reviewPoints ?? []"
    :evidence="report.evidence"
    :show-heading="false"
    @open-evidence="emit('openEvidence', $event)"
  />
  <p v-else-if="item.block.type === 'summary'" class="summary-text">{{ report.summary }}</p>
  <div v-else-if="item.block.type === 'changes'" class="change-grid">
    <div v-for="change in report.changes" :key="change.label" class="change-item">
      <span class="muted small">{{ change.label }}</span>
      <div>
        <span class="before-value">{{ change.before }}</span>
        <ArrowRight :size="16" /><strong>{{ change.after }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.summary-text {
  white-space: pre-wrap;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
h3 {
  font-size: 17px;
  margin: 24px 0 12px;
}
</style>
