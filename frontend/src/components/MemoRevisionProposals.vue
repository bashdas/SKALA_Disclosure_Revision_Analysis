<script setup lang="ts">
import { ArrowUpRight, ExternalLink, Link2 } from 'lucide-vue-next'
import { impactLabels, type Evidence, type Finding } from '../types/domain'
const props = withDefaults(defineProps<{ findings: Finding[]; evidence: Evidence[]; headingTag?: 'h2' | 'h3' }>(), { headingTag: 'h2' })
const emit = defineEmits<{
  openMemo: [paragraph: number | null]
  openEvidence: [source: Evidence]
}>()
function openEvidence(id: string) {
  const source = props.evidence.find((e) => e.id === id)
  if (source) emit('openEvidence', source)
}
function evidenceNumber(id: string) {
  const index = props.evidence.findIndex((e) => e.id === id)
  return index < 0 ? null : index + 1
}
function suggestionText(finding: Finding) {
  const normalize = (text: string) => text.replace(/\s+/g, ' ').trim()
  if (
    finding.impactType === 'NO_IMPACT' ||
    (normalize(finding.beforeText) && normalize(finding.beforeText) === normalize(finding.suggestion))
  ) return '기존 메모 문장을 유지합니다.'
  return finding.suggestion
}
</script>
<template>
  <section class="memo-proposals" aria-label="메모수정 제안">
    <component :is="headingTag">
      메모수정 제안 <span class="count">{{ findings.length }}</span>
    </component>
    <article v-for="(finding, i) in findings" :key="finding.id" class="finding-card surface">
      <div class="finding-header">
        <span class="finding-number">{{ String(i + 1).padStart(2, '0') }}</span
        ><span class="impact-tag" :class="finding.impactType.toLowerCase()">{{
          impactLabels[finding.impactType]
        }}</span>
      </div>
      <div class="finding-comparison">
        <div class="before-block">
          <span class="eyebrow">기존 메모의 문장</span>
          <blockquote>{{ finding.beforeText }}</blockquote>
          <button class="text-button" @click="emit('openMemo', finding.memoParagraph)">
            원문 문맥 확인 <ArrowUpRight :size="13" />
          </button>
        </div>
        <div class="after-block">
          <span class="eyebrow">새롭게 확인한 사실</span>
          <p>{{ finding.newFact }}</p>
        </div>
      </div>
      <div class="finding-explanation">
        <div>
          <h3>판단 이유</h3>
          <p>{{ finding.reason }}</p>
        </div>
        <div>
          <h3>수정 제안</h3>
          <p>{{ suggestionText(finding) }}</p>
        </div>
      </div>
      <div class="evidence-chips">
        <span class="small muted"><Link2 :size="13" /> 연결 근거</span
        ><button
          v-for="id in finding.evidenceIds"
          :key="id"
          :disabled="evidenceNumber(id) === null"
          :title="evidence.find((e) => e.id === id)?.title"
          :aria-label="
            evidenceNumber(id) === null ? '근거 확인 불가' : `근거 ${evidenceNumber(id)} 상세 보기`
          "
          @click="openEvidence(id)"
        >
          {{ evidenceNumber(id) === null ? '근거 확인 불가' : `근거 ${evidenceNumber(id)}` }}
          <ExternalLink v-if="evidenceNumber(id) !== null" :size="12" />
        </button>
      </div>
    </article>
  </section>
</template>
<style scoped>
.memo-proposals {
  margin-top: 32px;
  min-width: 0;
}
.memo-proposals > h2 {
  margin: 0 0 16px;
  font-size: 21px;
}
.memo-proposals > h3 {
  margin: 0 0 16px;
  font-size: 17px;
}
.evidence-chips button {
  white-space: nowrap;
}
.evidence-chips button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
</style>
