<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Activity, Sparkles, ArrowUpRight } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import { statusLabels } from '../types/domain'
import StatusPill from './StatusPill.vue'
import UiSelect from './UiSelect.vue'
import EmptyState from './EmptyState.vue'
const props = defineProps<{ companyId: string }>()
const store = useWorkspace(),
  status = ref('')
const reportsByTask = computed(
  () => new Map(store.savedReports.map((report) => [report.taskId, report])),
)
const tasks = computed(() =>
  store.tasks
    .filter((t) => t.companyId === props.companyId && (!status.value || t.status === status.value))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .map((task) => {
      const report = reportsByTask.value.get(task.id)
      return {
        ...task,
        report,
        title:
          store.filings.find((f) => f.id === task.filingId)?.title ||
          (task.disclosureReceiptNo
            ? `공시 ${task.disclosureReceiptNo} 분석`
            : report?.title || '공시 분석'),
        memoTitle: store.memos.find((m) => m.id === task.memoId)?.title || '기준 메모 확인 불가',
      }
    }),
)
</script>
<template>
  <div class="list-heading">
    <h2>
      AI 보고서 <span class="count">{{ tasks.length }}</span>
    </h2>
    <div class="filters">
      <span class="sr-only">분석 상태</span
      ><UiSelect
        v-model="status"
        aria-label="분석 상태"
        :options="[
          { label: '전체 상태', value: '' },
          ...Object.entries(statusLabels).map(([value, label]) => ({ value, label })),
        ]"
      />
    </div>
  </div>
  <div class="analysis-list">
    <article v-for="task in tasks" :key="task.id" class="analysis-row">
      <span class="document-icon" :class="{ mint: task.report }">
        <Sparkles v-if="task.report" :size="20" /><Activity v-else :size="20" />
      </span>
      <div class="document-info">
        <h3>
          <RouterLink :to="`/analyses/${task.id}`" class="document-title">{{
            task.title
          }}</RouterLink>
        </h3>
        <p class="small muted analysis-summary-meta">
          <span>{{ task.memoTitle }} · 기준 v{{ task.baseMemoVersion }}</span>
          <span>{{ date(task.createdAt, true) }}</span>
        </p>
      </div>
      <div class="document-actions">
        <StatusPill
          v-if="!task.report && task.status !== 'COMPLETED_WITH_WARNINGS'"
          :status="task.status"
        />
        <RouterLink
          :to="`/analyses/${task.id}`"
          class="icon-button"
          :aria-label="`${task.title} ${task.report ? '보고서' : '분석'} 열기`"
          :title="task.report ? '보고서 열기' : '분석 열기'"
        >
          <ArrowUpRight :size="18" />
        </RouterLink>
      </div>
    </article>
  </div>
  <EmptyState
    v-if="!tasks.length"
    :title="status ? '해당 상태의 분석이 없습니다' : '아직 분석이 없습니다'"
    :message="
      status ? '다른 상태를 선택해 주세요.' : '이 종목의 공시와 기준 메모로 분석을 시작하세요.'
    "
  />
</template>

<style scoped>
.analysis-summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.analysis-summary-meta > span:last-child {
  white-space: nowrap;
}
</style>
