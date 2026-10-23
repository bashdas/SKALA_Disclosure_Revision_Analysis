<script setup lang="ts">
import { computed } from 'vue'
import type { Evidence, Perspective, ReviewReport } from '../types/domain'
import { reportHeading } from '../lib/report-layout'
import { reportPresentation } from '../lib/report-presentation'
import ReportSection from './ReportSection.vue'
import ReportContent from './ReportContent.vue'
import MarkdownReport from './MarkdownReport.vue'
import PerspectiveAnalysis from './PerspectiveAnalysis.vue'

const props = defineProps<{ report: ReviewReport; perspectives: Perspective[] }>()
const emit = defineEmits<{
  openEvidence: [source: Evidence]
  openMemo: [paragraph: number | null]
}>()
const presentation = computed(() => reportPresentation(props.report, props.perspectives))
const analysis = computed(() =>
  presentation.value.sections
    .find((s) => s.id === 'analysis')!
    .blocks.flatMap(({ block }) => (block.type === 'perspective-analysis' ? block.ranges : [])),
)
const hasReviews = computed(() =>
  presentation.value.sections
    .find((s) => s.id === 'reviews')!
    .blocks.some(
      ({ block }) =>
        block.type === 'review-points' ||
        (block.type === 'markdown' && reportHeading(block.heading) === '새롭게고찰할관점'),
    ),
)
const emptyText = {
  summary: '저장된 핵심 요약이 없습니다.',
  facts: '저장된 공시 내용이 없습니다.',
  limits: '저장된 확인 범위와 질문이 없습니다.',
  sources: '저장된 출처와 원문 인용이 없습니다.',
  history: '저장된 과거 공시 조회 기록이 없습니다.',
}
</script>

<template>
  <div class="unified-report-content">
    <slot />
    <MarkdownReport
      v-for="(block, i) in presentation.intro"
      :key="`intro-${i}`"
      :content="report.content"
      :range="block.type === 'markdown' ? block.range : undefined"
      hide-report-title
      :evidence="report.evidence"
      @open-evidence="emit('openEvidence', $event)"
    />
    <template v-for="section in presentation.sections" :key="section.id">
      <PerspectiveAnalysis
        v-if="section.id === 'analysis'"
        :report="report"
        :perspectives="perspectives"
        :ranges="analysis"
        :results="presentation.fallbackResults"
        @open-evidence="emit('openEvidence', $event)"
      />
      <ReportSection
        v-else
        :title="section.title"
        :count="
          section.id === 'reviews' && hasReviews && report.reviewPoints?.length
            ? report.reviewPoints.length
            : undefined
        "
        :collapsible="section.collapsed"
        :default-open="false"
        :class="[
          section.collapsed ? 'report-detail' : 'report-main',
          section.id === 'summary' ? 'report-summary-section' : `report-${section.id}`,
        ]"
      >
        <template v-if="section.id === 'reviews' && !hasReviews">
          <p class="muted report-empty">이 보고서에는 별도의 재검토 관점이 저장되지 않았습니다.</p>
          <div
            v-if="!report.findings.length"
            data-testid="memo-review-decision"
            class="memo-review-record"
          >
            <h3>
              {{ report.memoReview?.status === 'KEEP' ? '기존 메모 유지' : '메모 영향 판단 보류' }}
            </h3>
            <p>
              {{
                report.memoReview?.reason ||
                '유지 또는 수정 여부를 확인할 판단 근거가 없습니다. 재분석이 필요합니다.'
              }}
            </p>
            <div class="evidence-chips">
              <button
                v-for="source in report.evidence.filter((e) =>
                  report.memoReview?.evidenceIds.includes(e.id),
                )"
                :key="source.id"
                @click="emit('openEvidence', source)"
              >
                {{ source.title }}
              </button>
            </div>
          </div>
        </template>
        <ReportContent
          v-for="(item, i) in section.blocks"
          :key="i"
          :item="item"
          :report="report"
          @open-evidence="emit('openEvidence', $event)"
          @open-memo="emit('openMemo', $event)"
        />
        <template v-if="!section.blocks.length && section.id !== 'reviews'">
          <ul v-if="section.id === 'limits' && report.warnings.length" class="report-warnings">
            <li v-for="(warning, i) in report.warnings" :key="i">{{ warning }}</li>
          </ul>
          <div
            v-else-if="section.id === 'sources' && report.evidence.length"
            class="report-evidence"
          >
            <article v-for="(source, i) in report.evidence" :key="source.id">
              <h3>
                <button class="text-button" @click="emit('openEvidence', source)">
                  근거 {{ i + 1 }} · {{ source.title }}
                </button>
              </h3>
              <p class="muted small">{{ source.location }}</p>
              <blockquote>{{ source.quote || source.context }}</blockquote>
              <a
                v-if="source.url && /^https?:\/\//i.test(source.url)"
                :href="source.url"
                target="_blank"
                rel="noopener noreferrer"
                >외부 원문 열기</a
              >
            </article>
          </div>
          <p v-else class="muted report-empty">{{ emptyText[section.id] }}</p>
        </template>
      </ReportSection>
    </template>
  </div>
</template>

<style scoped>
.unified-report-content {
  padding: 0 24px 24px;
}
.unified-report-content :deep(.markdown-body) {
  padding: 0;
}
.report-main {
  margin-top: 32px;
}
.report-main :deep(.report-fold-heading h2),
.report-main :deep(.report-section-title) {
  font-size: 21px;
}
.report-main :deep(.report-fold-content) {
  padding-top: 14px;
}
.report-reviews :deep(.review-points) {
  margin-top: 0;
}
.report-detail {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.report-empty {
  line-height: 1.85;
  margin: 0;
}
.memo-review-record h3,
.report-evidence h3 {
  font-size: 17px;
  margin: 20px 0 12px;
}
.report-evidence article + article {
  margin-top: 24px;
}
.report-evidence blockquote {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 12px 0;
}
.report-evidence a {
  color: var(--primary);
}
.report-warnings {
  line-height: 1.85;
}
@media (max-width: 650px) {
  .unified-report-content {
    padding-inline: 20px;
  }
}
</style>
