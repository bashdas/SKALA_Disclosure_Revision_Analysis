<script setup lang="ts">
import { toast, notifyError } from '../lib/notifications'
import { computed, nextTick, watch, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  AlertTriangle,
  LoaderCircle,
  FileText,
  Download,
  ArrowRight,
} from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import { stages, stageLabels } from '../types/domain'
import ReportSection from '../components/ReportSection.vue'
import SkeletonState from '../components/SkeletonState.vue'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'
import AnalysisPerspectives from '../components/AnalysisPerspectives.vue'
import ReportBody from '../components/ReportBody.vue'
import { downloadReport } from '../services/http'
const store = useWorkspace(),
  route = useRoute()
const task = computed(() => store.tasks.find((t) => t.id === route.params.taskId))
const report = computed(() => store.reports.find((r) => r.taskId === task.value?.id))
const memo = computed(() => store.memos.find((m) => m.id === task.value?.memoId))
const filing = computed(() => store.filings.find((f) => f.id === task.value?.filingId))
const stageIndex = computed(() =>
  task.value?.currentStage ? stages.indexOf(task.value.currentStage) : -1,
)
const inProgress = computed(
  () => !!task.value && ['CREATED', 'QUEUED', 'RUNNING', 'SAVING'].includes(task.value.status),
)
watch(
  () => [report.value?.id, report.value?.savedAt],
  async () => {
    await nextTick()
    if (report.value?.savedAt)
      await store.markRead({ kind: 'report', id: report.value.id, version: report.value.version })
  },
  { immediate: true, flush: 'post' },
)
const exporting = ref(''),
  exportError = ref('')
async function download(extension: 'md' | 'pdf') {
  if (!task.value || exporting.value) return
  exporting.value = extension
  exportError.value = ''
  try {
    await downloadReport(task.value.id, extension)
    toast.success('보고서를 다운로드했습니다.')
  } catch (e) {
    notifyError(e)
    exportError.value = e instanceof Error ? e.message : '다운로드 실패'
  } finally {
    exporting.value = ''
  }
}
</script>
<template>
  <template v-if="task">
    <RouterLink
      :to="task.companyId ? `/companies/${task.companyId}?tab=reports` : '/companies'"
      class="back-link"
      ><ArrowLeft :size="15" /> {{ store.companyName(task.companyId) }}</RouterLink
    >
    <div class="page-heading report-heading">
      <div>
        <h1>
          {{ store.companyName(task.companyId) }} <span class="heading-light">영향 분석</span>
        </h1>
        <p class="page-description">{{ filing?.title }}</p>
      </div>
      <StatusPill :status="task.status" />
    </div>
    <div class="report-context">
      <span
        ><FileText :size="15" />기준 메모
        <button class="text-button" @click="store.openMemo(task.memoId, task.baseMemoVersion)">
          {{ memo?.title ?? '기준 메모' }} , v{{ task.baseMemoVersion }}
        </button></span
      ><span>자료 기준 {{ date(task.asOf, true) }}</span>
    </div>
    <section
      v-if="!['COMPLETED', 'COMPLETED_WITH_WARNINGS'].includes(task.status)"
      class="surface progress-section"
      aria-label="분석 진행"
    >
      <div class="section-heading">
        <h2>{{ inProgress ? '근거를 연결하고 있습니다' : '분석 진행 기록' }}</h2>
        <span v-if="inProgress" class="running-text" role="status"
          ><LoaderCircle :size="14" class="spin" />{{
            task.currentStage ? stageLabels[task.currentStage] : '대기'
          }}</span
        >
      </div>
      <ol class="stage-list">
        <li
          v-for="(stage, i) in stages"
          :key="stage"
          :class="{
            done:
              i < stageIndex ||
              (i === stageIndex && ['COMPLETED', 'COMPLETED_WITH_WARNINGS'].includes(task.status)),
            current: i === stageIndex && inProgress,
            failed: stage === task.errorStage,
          }"
        >
          <span class="stage-symbol"
            ><Check
              v-if="
                i < stageIndex ||
                (i === stageIndex && ['COMPLETED', 'COMPLETED_WITH_WARNINGS'].includes(task.status))
              "
              :size="14"
            /><AlertTriangle v-else-if="stage === task.errorStage" :size="13" /><LoaderCircle
              v-else-if="i === stageIndex && inProgress"
              :size="14"
              class="spin"
            /><span v-else>{{ i + 1 }}</span></span
          ><span>{{ stageLabels[stage] }}</span>
        </li>
      </ol>
    </section>
    <div v-if="task.status === 'FAILED'" class="error-banner" role="alert">
      <AlertTriangle :size="21" />
      <div>
        <h2>분석을 완료하지 못했습니다</h2>
        <p>{{ task.errorMessage }}</p>
        <p class="small">
          실패 단계: {{ task.errorStage ? stageLabels[task.errorStage] : '확인 불가' }} , 성공한
          보고서로 저장되지 않았습니다.
        </p>
        <RouterLink :to="`/companies/${task.companyId}`" class="text-button"
          >자료를 확인하고 다시 분석 <ArrowRight :size="14"
        /></RouterLink>
      </div>
    </div>
    <div v-if="task.status === 'SAVE_FAILED'" class="error-banner" role="alert">
      <AlertTriangle :size="21" />
      <div>
        <h2>보고서가 아직 저장되지 않았습니다</h2>
        <p>
          서버의 저장 실패 상태입니다. AI Worker의 보존된 체크포인트에서 저장을 재시도해야 합니다.
        </p>
      </div>
    </div>
    <ReportSection
      v-if="report"
      title="공시 영향 분석 보고서"
      :collapsible="false"
      class="surface unified-report"
      aria-label="공시 영향 분석 보고서"
    >
      <template #actions>
        <span v-if="report.savedAt" class="saved-label"
          ><CheckCircle2 :size="14" />{{ date(report.savedAt, true) }} 저장</span
        >
        <span v-else class="warning-text">미저장</span>
        <div class="row-actions">
          <button class="button secondary" :disabled="!!exporting" @click="download('md')">
            <Download :size="15" />MD 다운로드
          </button>
          <button class="button primary" :disabled="!!exporting" @click="download('pdf')">
            <Download :size="15" />{{ exporting === 'pdf' ? 'PDF 생성 중…' : 'PDF 다운로드' }}
          </button>
        </div>
      </template>
      <ReportBody
        :key="report.id"
        :report="report"
        :perspectives="task.perspectives"
        @open-evidence="store.openEvidence"
        @open-memo="store.openMemo(task.memoId, task.baseMemoVersion, $event)"
      >
        <p v-if="exportError" class="inline-warning" role="alert">{{ exportError }}</p>
      </ReportBody>
    </ReportSection>
    <div v-else-if="inProgress" class="analysis-wait" role="status">
      <SkeletonState variant="report" />
      <h2>기존 논리와 새로운 사실을 비교하고 있어요</h2>
      <p>단계가 완료되면 이곳에 서버 보고서가 표시됩니다.</p>
    </div>
    <ReportSection
      v-if="!report && task.currentStage && stageIndex >= 3"
      title="선택한 분석 관점"
      class="surface perspectives-section"
    >
      <AnalysisPerspectives :perspectives="task.perspectives" :show-heading="false" />
    </ReportSection>
  </template>
  <EmptyState
    v-else
    title="분석 작업을 찾을 수 없습니다"
    message="현재 계정에서 조회할 수 있는 작업인지 확인해 주세요."
    ><RouterLink to="/companies" class="button secondary">기업 목록</RouterLink></EmptyState
  >
</template>

<style scoped>
.unified-report {
  margin: 28px 0 30px;
}
.unified-report > :deep(.report-fold-heading .report-section-title) {
  font-size: 26px;
  line-height: 1.5;
  letter-spacing: -0.025em;
}
</style>
