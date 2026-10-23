<script setup lang="ts">
import { ExternalLink } from 'lucide-vue-next'
import type { Evidence, ReviewPoint } from '../types/domain'
const props = defineProps<{ points: ReviewPoint[]; evidence: Evidence[] }>()
const emit = defineEmits<{ openEvidence: [source: Evidence] }>()
function sources(point: ReviewPoint) {
  return point.evidenceIds.flatMap((id) => {
    const index = props.evidence.findIndex((source) => source.id === id)
    return index < 0 ? [] : [{ source: props.evidence[index]!, number: index + 1 }]
  })
}
</script>

<template>
  <section class="review-points" aria-label="새롭게 고찰할 관점">
    <h2>
      새롭게 고찰할 관점 <span class="count">{{ points.length }}</span>
    </h2>
    <article v-for="(point, i) in points" :key="i" class="finding-card surface">
      <div class="review-heading">
        <span class="finding-number">{{ String(i + 1).padStart(2, '0') }}</span>
        <h3>{{ point.title }}</h3>
      </div>
      <div class="finding-comparison">
        <div class="before-block">
          <span class="eyebrow">기존 메모의 관점과 가정</span>
          <p>{{ point.memoView }}</p>
        </div>
        <div class="after-block">
          <span class="eyebrow">새 공시에서 확인한 사실</span>
          <p>{{ point.disclosureFact }}</p>
        </div>
      </div>
      <div class="review-reason">
        <h4>다시 고찰할 이유</h4>
        <p>{{ point.reason }}</p>
      </div>
      <div class="review-question">
        <h4>검토 질문</h4>
        <p>{{ point.question }}</p>
      </div>
      <div class="review-checks">
        <h4>확인할 자료와 조건</h4>
        <ul>
          <li v-for="(item, j) in point.checkItems" :key="j">{{ item }}</li>
        </ul>
      </div>
      <div class="evidence-chips">
        <span class="small muted">메모와 공시의 연결 근거</span>
        <button
          v-for="{ source, number } in sources(point)"
          :key="source.id"
          :aria-label="`근거 ${number} 상세 보기`"
          :title="source.title"
          @click="emit('openEvidence', source)"
        >
          근거 {{ number }} <ExternalLink :size="12" />
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.review-points {
  margin-top: 32px;
  min-width: 0;
}
.review-points > h2 {
  margin: 0 0 16px;
  font-size: 21px;
}
.review-heading {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 20px;
}
.review-heading h3 {
  margin: 0;
  font-size: 18px;
}
.review-reason,
.review-question,
.review-checks {
  margin-top: 20px;
}
h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
p,
li {
  line-height: 1.8;
  overflow-wrap: anywhere;
}
p {
  margin: 0;
  white-space: pre-line;
}
ul {
  margin: 0;
  padding-left: 20px;
}
.evidence-chips {
  margin-top: 24px;
}
.evidence-chips button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
</style>
