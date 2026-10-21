<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ArrowLeft,
  FileText,
  StickyNote,
  Sparkles,
  ArrowUpRight,
  Link2,
  Check,
  Activity,
} from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import AnalysisLauncher from '../components/AnalysisLauncher.vue'
import EmptyState from '../components/EmptyState.vue'
import MemoUpload from '../components/MemoUpload.vue'
import CompanyAnalysisHistory from '../components/CompanyAnalysisHistory.vue'
const store = useWorkspace(),
  route = useRoute(),
  preferredFiling = ref(''),
  memoSearch = ref('')
const company = computed(() => store.companies.find((c) => c.id === route.params.companyId))
const tab = computed(() =>
  ['filings', 'memos', 'reports', 'history'].includes(String(route.query.tab))
    ? String(route.query.tab)
    : 'filings',
)
const companyFilings = computed(() =>
  store.filings.filter((f) => f.companyId === company.value?.id),
)
const companyMemos = computed(() =>
  store.memos.filter((m) => m.companyName === company.value?.name),
)
const filteredMemos = computed(() =>
  companyMemos.value.filter((m) => m.title.includes(memoSearch.value)),
)
const companyTasks = computed(() => store.tasks.filter((t) => t.companyId === company.value?.id))
const companyReports = computed(() =>
  store.savedReports.filter(
    (r) => store.tasks.find((t) => t.id === r.taskId)?.companyId === company.value?.id,
  ),
)
const tabs = computed(() => [
  { id: 'filings', name: '공시', icon: FileText, count: companyFilings.value.length },
  { id: 'memos', name: '메모 관리', icon: StickyNote, count: companyMemos.value.length },
  { id: 'reports', name: 'AI 보고서', icon: Sparkles, count: companyReports.value.length },
  { id: 'history', name: '분석 이력', icon: Activity, count: companyTasks.value.length },
])
</script>
<template>
  <template v-if="company">
    <RouterLink to="/companies" class="back-link"><ArrowLeft :size="15" /> 기업 목록</RouterLink>
    <div class="company-detail-heading">
      <span class="company-logo" :class="company.id">{{ company.initials }}</span>
      <div>
        <p class="eyebrow">{{ company.sector }} · {{ company.code }}</p>
        <h1>{{ company.name }}</h1>
      </div>
    </div>
    <div class="detail-layout">
      <section class="document-section">
        <nav class="tabs" aria-label="기업 자료 종류">
          <RouterLink
            v-for="item in tabs"
            :key="item.id"
            :to="{ query: { ...route.query, tab: item.id } }"
            :class="{ selected: tab === item.id }"
            :aria-current="tab === item.id ? 'page' : undefined"
            ><component :is="item.icon" :size="16" />{{ item.name
            }}<span>{{ item.count }}</span></RouterLink
          >
        </nav>
        <template v-if="tab === 'filings'">
          <div class="list-heading">
            <h2>공시 업데이트</h2>
            <span class="small muted">최신순 · {{ companyFilings.length }}건</span>
          </div>
          <div v-if="company.id === 'shi'" class="context-note">
            <Link2 :size="16" /><span
              >즈베즈다 관련 공시 2건입니다. 각 계약과 접수번호를 구분해 확인하세요.</span
            >
          </div>
          <article v-for="filing in companyFilings" :key="filing.id" class="document-row">
            <span class="document-icon"><FileText :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">{{ filing.filingType }}</span
                ><span
                  v-if="
                    store.unread({ kind: 'filing', id: filing.id, version: filing.currentVersion })
                  "
                  class="new-dot"
                  >NEW</span
                ><span v-else class="read-label"><Check :size="12" /> 확인함</span>
              </div>
              <button class="document-title" @click="store.openFiling(filing.id)">
                {{ filing.title }}
              </button>
              <p class="small muted">
                {{ date(filing.filedAt) }} <span class="dot-separator">·</span>
                {{ filing.receiptNo ?? '접수번호 미확인 · 샘플' }}
              </p>
              <div class="row-actions">
                <button class="text-button" @click="store.openFiling(filing.id)">
                  내용 확인 <ArrowUpRight :size="13" /></button
                ><button class="text-button" @click="preferredFiling = filing.id">
                  분석에 사용 <Sparkles :size="13" />
                </button>
              </div>
            </div>
          </article>
          <EmptyState
            v-if="!companyFilings.length"
            title="등록된 공시가 없습니다"
            message="새 공시가 등록되면 이곳에 표시됩니다."
          />
        </template>
        <template v-else-if="tab === 'memos'">
          <div class="list-heading">
            <h2>기존 기업분석 메모</h2>
            <label class="sr-only" for="company-memo-search">메모 검색</label>
            <input
              id="company-memo-search"
              v-model="memoSearch"
              type="search"
              class="compact-search"
              placeholder="이 종목의 메모 검색"
            />
          </div>
          <article v-for="memo in filteredMemos" :key="memo.id" class="document-row">
            <span class="document-icon"><StickyNote :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">시연용 사내 메모</span
                ><span
                  v-if="store.unread({ kind: 'memo', id: memo.id, version: memo.currentVersion })"
                  class="new-dot"
                  >NEW</span
                >
              </div>
              <button class="document-title" @click="store.openMemo(memo.id)">
                {{ memo.title }}
              </button>
              <p class="small muted">
                {{ date(memo.updatedAt) }} · v{{ memo.currentVersion }} ·
                {{ memo.versions.length }}개 버전
              </p>
              <button class="text-button" @click="store.openMemo(memo.id)">
                본문·버전 확인 <ArrowUpRight :size="13" />
              </button>
            </div>
          </article>
          <EmptyState
            v-if="!filteredMemos.length"
            title="표시할 메모가 없습니다"
            message="검색 조건을 바꾸거나 이 종목의 기준 메모를 추가하세요."
          />
        </template>
        <CompanyAnalysisHistory
          v-else-if="tab === 'history'"
          :key="company.id"
          :company-id="company.id"
        />
        <template v-else>
          <div class="list-heading">
            <h2>저장된 분석 보고서</h2>
            <span class="small muted">시연용 분석 결과</span>
          </div>
          <article v-for="report in companyReports" :key="report.id" class="document-row">
            <span class="document-icon mint"><Sparkles :size="20" /></span>
            <div class="document-info">
              <div class="inline-meta">
                <span class="tag">AI 보고서 · 샘플</span
                ><span
                  v-if="store.unread({ kind: 'report', id: report.id, version: report.version })"
                  class="new-dot"
                  >NEW</span
                >
              </div>
              <RouterLink class="document-title" :to="`/analyses/${report.taskId}`">{{
                report.title
              }}</RouterLink>
              <p class="small muted">{{ date(report.savedAt) }} · 원본 메모 보존</p>
              <RouterLink class="text-button" :to="`/analyses/${report.taskId}`"
                >결과 확인 <ArrowUpRight :size="13"
              /></RouterLink>
            </div>
          </article>
          <EmptyState
            v-if="!companyReports.length"
            title="저장된 보고서가 없습니다"
            message="공시와 메모를 선택해 첫 분석을 시작하세요."
          />
        </template>
      </section>
      <MemoUpload
        v-if="tab === 'memos'"
        :key="`upload-${company.id}`"
        :company-id="company.id"
        :company-name="company.name"
      />
      <AnalysisLauncher
        v-else
        :key="company.id"
        :company-id="company.id"
        :preferred-filing="preferredFiling"
      />
    </div>
  </template>
  <EmptyState v-else title="기업을 찾을 수 없습니다" message="기업 목록에서 다시 선택해 주세요."
    ><RouterLink to="/companies" class="button secondary">기업 목록</RouterLink></EmptyState
  >
</template>
