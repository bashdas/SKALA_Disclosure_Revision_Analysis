<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Activity, ArrowUpRight } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import { statusLabels } from '../types/domain'
import StatusPill from './StatusPill.vue'
import EmptyState from './EmptyState.vue'
const props = defineProps<{ companyId: string }>()
const store = useWorkspace(),
  status = ref('')
const tasks = computed(() =>
  store.tasks
    .filter((t) => t.companyId === props.companyId && (!status.value || t.status === status.value))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
)
</script>
<template>
  <div class="list-heading">
    <h2>
      분석 이력 <span class="count">{{ tasks.length }}</span>
    </h2>
    <label class="filters"
      ><span class="sr-only">분석 상태</span
      ><select v-model="status" aria-label="분석 상태">
        <option value="">전체 상태</option>
        <option v-for="(label, key) in statusLabels" :key="key" :value="key">{{ label }}</option>
      </select></label
    >
  </div>
  <div class="analysis-list">
    <RouterLink
      v-for="task in tasks"
      :key="task.id"
      :to="`/analyses/${task.id}`"
      class="analysis-row"
    >
      <span class="document-icon"><Activity :size="20" /></span>
      <div class="document-info">
        <div class="inline-meta">
          <strong>{{ store.companyName(task.companyId) }}</strong
          ><span class="small muted">{{ date(task.createdAt, true) }}</span>
        </div>
        <h3>{{ store.filings.find((f) => f.id === task.filingId)?.title }}</h3>
        <p class="small muted">
          {{ store.memos.find((m) => m.id === task.memoId)?.title }} · 기준 v{{
            task.baseMemoVersion
          }}
        </p>
      </div>
      <StatusPill :status="task.status" /><ArrowUpRight :size="18" class="muted" />
    </RouterLink>
  </div>
  <EmptyState
    v-if="!tasks.length"
    title="해당하는 분석이 없습니다"
    message="상태 필터를 바꾸거나 이 종목의 공시와 메모로 분석을 시작하세요."
  />
</template>
