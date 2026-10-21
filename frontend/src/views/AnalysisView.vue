<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ArrowLeft,
  ArrowUpRight as ArrowUpRightIcon,
  Check,
  CheckCircle2,
  AlertTriangle,
  LoaderCircle,
  RefreshCw,
  FileText,
  ArrowRight,
  Link2,
  ExternalLink,
  Building2,
  Calculator,
  ShieldCheck,
  Sparkles,
  LockKeyhole,
} from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import {
  stages,
  stageLabels,
  perspectiveLabels,
  perspectiveStatusLabels,
  impactLabels,
} from '../types/domain'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'
const store = useWorkspace(),
  route = useRoute(),
  saving = ref(false),
  saveError = ref('')
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
const icons: Record<string, typeof Building2> = {
  BUSINESS_INDUSTRY: Building2,
  FINANCE: Calculator,
  EXTERNAL_RISK: ShieldCheck,
}
watch(
  () => [report.value?.id, report.value?.savedAt],
  async () => {
    await nextTick()
    if (report.value?.savedAt)
      await store.markRead({ kind: 'report', id: report.value.id, version: report.value.version })
  },
  { immediate: true, flush: 'post' },
)
async function retry() {
  if (!task.value || saving.value) return
  saving.value = true
  saveError.value = ''
  try {
    await store.retrySave(task.value.id)
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '저장 실패'
  } finally {
    saving.value = false
  }
}
function evidence(id: string) {
  const e = report.value?.evidence.find((e) => e.id === id)
  if (e) store.openEvidence(e)
}
</script>
<template>
  <template v-if="task">
    <RouterLink :to="`/companies/${task.companyId}?tab=reports`" class="back-link"
      ><ArrowLeft :size="15" /> {{ store.companyName(task.companyId) }}</RouterLink
    >
    <div class="page-heading report-heading">
      <div>
        <p class="eyebrow">RESEARCH IMPACT REVIEW</p>
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
          {{ memo?.title }} · v{{ task.baseMemoVersion }}
        </button></span
      ><span>자료 기준 {{ date(task.asOf, true) }}</span>
    </div>
    <p class="sample-note">
      UI 시연용 분석 보고서입니다. 실제 Agent 실행·외부 API 조회·서버 저장 결과가 아닙니다.
    </p>
    <section class="surface progress-section" aria-label="분석 진행">
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
          실패 단계: {{ task.errorStage ? stageLabels[task.errorStage] : '확인 불가' }} · 성공한
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
          생성된 내용은 아래에서 확인할 수 있습니다. 분석을 다시 실행하지 않고 저장만 재시도합니다.
        </p>
        <p v-if="saveError" class="field-error">{{ saveError }}</p>
        <button class="button secondary" :disabled="saving" @click="retry">
          <RefreshCw :size="15" />{{ saving ? '저장 중…' : '보고서 저장 재시도' }}
        </button>
      </div>
    </div>
    <section v-if="task.currentStage && stageIndex >= 3" class="perspectives-section">
      <div class="section-heading">
        <h2>선택한 분석 관점</h2>
        <span class="small muted">필요한 관점만 실행합니다</span>
      </div>
      <div class="perspective-grid">
        <article
          v-for="p in task.perspectives"
          :key="p.type"
          class="perspective-card"
          :class="{ unselected: !p.selected }"
        >
          <div class="perspective-header">
            <component :is="icons[p.type] ?? ShieldCheck" :size="18" />
            <h3>{{ perspectiveLabels[p.type] ?? p.type }}</h3>
            <span
              class="tag"
              :class="{
                warning: ['INSUFFICIENT_EVIDENCE', 'LIMIT_REACHED', 'FAILED'].includes(p.status),
              }"
              >{{ p.selected ? perspectiveStatusLabels[p.status] : '선택 안 함' }}</span
            >
          </div>
          <p>{{ p.selectionReason }}</p>
          <p v-if="p.result" class="perspective-result">{{ p.result }}</p>
        </article>
      </div>
    </section>
    <template v-if="report">
      <section class="report-summary surface">
        <div class="report-title-row">
          <span class="eyebrow"><Sparkles :size="15" /> 검토 보고서 · 샘플</span
          ><span v-if="report.savedAt" class="saved-label"
            ><CheckCircle2 :size="14" />{{ date(report.savedAt, true) }} 저장</span
          ><span v-else class="warning-text">미저장</span>
        </div>
        <h2>{{ report.title }}</h2>
        <p class="summary-text">{{ report.summary }}</p>
        <div class="change-grid">
          <div v-for="change in report.changes" :key="change.label" class="change-item">
            <span class="muted small">{{ change.label }}</span>
            <div>
              <span class="before-value">{{ change.before }}</span
              ><ArrowRight :size="16" /><strong>{{ change.after }}</strong>
            </div>
          </div>
        </div>
      </section>
      <section class="findings-section">
        <div class="section-heading">
          <h2>
            기존 논리의 재검토 <span class="count">{{ report.findings.length }}</span>
          </h2>
          <span class="small muted">기준 메모 v{{ task.baseMemoVersion }}와 비교</span>
        </div>
        <article
          v-for="(finding, i) in report.findings"
          :key="finding.id"
          class="finding-card surface"
        >
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
              <button
                class="text-button"
                @click="store.openMemo(task.memoId, task.baseMemoVersion, finding.memoParagraph)"
              >
                원문 문맥 확인 <ArrowUpRightIcon :size="13" />
              </button>
            </div>
            <div class="after-block">
              <span class="eyebrow">새롭게 확인한 사실 · 시연</span>
              <p>{{ finding.newFact }}</p>
            </div>
          </div>
          <div class="finding-explanation">
            <div>
              <h3>판단 이유</h3>
              <p>{{ finding.reason }}</p>
            </div>
            <div>
              <h3>검토 제안</h3>
              <p>{{ finding.suggestion }}</p>
            </div>
          </div>
          <div class="evidence-chips">
            <span class="small muted"><Link2 :size="13" /> 연결 근거</span
            ><button v-for="id in finding.evidenceIds" :key="id" @click="evidence(id)">
              {{ report.evidence.find((e) => e.id === id)?.title }}<ExternalLink :size="12" />
            </button>
          </div>
        </article>
      </section>
      <section class="warning-section">
        <div class="section-heading">
          <h2><AlertTriangle :size="18" /> 추가 확인 사항</h2>
          <span class="tag warning">확정 판단과 구분</span>
        </div>
        <ul>
          <li v-for="warning in report.warnings" :key="warning">{{ warning }}</li>
          <li v-if="report.noAdditionalAnalysisReason">{{ report.noAdditionalAnalysisReason }}</li>
        </ul>
      </section>
      <section class="surface source-list">
        <div class="list-heading">
          <h2>
            근거 자료 <span class="count">{{ report.evidence.length }}</span>
          </h2>
          <span class="small muted">출처·시점·원문 위치</span>
        </div>
        <button
          v-for="source in report.evidence"
          :key="source.id"
          class="source-row"
          @click="store.openEvidence(source)"
        >
          <FileText :size="17" /><span
            ><strong>{{ source.title }}</strong
            ><span class="small muted"
              >{{ date(source.publishedAt) }} · {{ source.location }}</span
            ></span
          ><ExternalLink :size="15" />
        </button>
      </section>
      <p class="preserve-note report-preserve">
        <LockKeyhole :size="14" />이 보고서는 별도 자료입니다. 기존 메모의 내용·버전은 변경되지
        않았습니다.
      </p>
    </template>
    <div v-else-if="inProgress" class="analysis-wait" role="status">
      <span class="launcher-icon"><Sparkles :size="24" /></span>
      <h2>기존 논리와 새로운 사실을 비교하고 있어요</h2>
      <p>단계가 완료되면 이곳에 시연 보고서가 표시됩니다.</p>
    </div>
  </template>
  <EmptyState
    v-else
    title="분석 작업을 찾을 수 없습니다"
    message="새로고침하면 실행 중인 샘플 작업이 초기화됩니다. 분석 이력에서 다시 선택해 주세요."
    ><RouterLink to="/companies" class="button secondary">기업 목록</RouterLink></EmptyState
  >
</template>
