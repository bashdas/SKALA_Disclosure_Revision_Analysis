<script setup lang="ts">
import { FileText, StickyNote, Sparkles, Clock3, ArrowRight, Star } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { useWorkspace } from '../stores/workspace'
import { date } from '../lib/format'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'
import { usePreferences } from '../stores/preferences'
const store = useWorkspace(),
  preferences = usePreferences()
const categories = [
  { kind: 'filing', tab: 'filings', label: '공시', icon: FileText },
  { kind: 'memo', tab: 'memos', label: '메모', icon: StickyNote },
  { kind: 'report', tab: 'reports', label: 'AI 보고서', icon: Sparkles },
] as const
function latest(id: string) {
  return [
    ...store.filings.filter((f) => f.companyId === id).map((f) => f.filedAt),
    ...store.memos.filter((m) => m.companyName === store.companyName(id)).map((m) => m.updatedAt),
    ...store.savedReports
      .filter((r) => store.tasks.find((t) => t.id === r.taskId)?.companyId === id)
      .map((r) => r.savedAt!),
  ]
    .sort()
    .at(-1)
}
function running(id: string) {
  return store.tasks.find(
    (t) => t.companyId === id && ['QUEUED', 'RUNNING', 'SAVING'].includes(t.status),
  )
}
</script>
<template>
  <div class="section-heading">
    <h1 class="company-list-title">
      리서치 기업 <span class="count">{{ store.companies.length }}</span>
    </h1>
    <span class="muted small">업데이트 배지를 눌러 새 자료를 확인하세요</span>
  </div>
  <div v-if="store.companies.length" class="company-grid">
    <article
      v-for="company in store.companies"
      :key="company.id"
      class="company-banner"
      :data-testid="`company-${company.id}`"
    >
      <button
        class="favorite-button company-favorite"
        :class="{ selected: preferences.isFavorite(company.id) }"
        :aria-label="`${company.name} 관심종목 ${preferences.isFavorite(company.id) ? '해제' : '추가'}`"
        :aria-pressed="preferences.isFavorite(company.id)"
        @click="preferences.toggleFavorite(company.id)"
      >
        <Star :size="19" />
      </button>
      <RouterLink
        class="company-entry"
        :to="`/companies/${company.id}`"
        :aria-label="`${company.name} 기업 상세`"
      >
        <div class="company-top">
          <span class="company-logo" :class="company.id">{{ company.initials }}</span
          ><span class="market-tag">KOSPI · {{ company.code }}</span>
        </div>
        <div class="company-name">
          <h2>{{ company.name }}</h2>
          <span>{{ company.sector }}</span>
        </div>
        <p class="company-description">{{ company.description }}</p>
      </RouterLink>
      <div class="update-grid">
        <RouterLink
          v-for="category in categories"
          :key="category.kind"
          :to="{ path: `/companies/${company.id}`, query: { tab: category.tab } }"
          class="update-item"
          :aria-label="`${company.name} ${category.label} 업데이트 ${store.countUnread(company.id, category.kind)}건`"
          :data-testid="`${company.id}-${category.kind}-badge`"
        >
          <span class="update-label"
            ><component :is="category.icon" :size="16" />{{ category.label }}</span
          ><span
            class="update-count"
            :class="{ unread: store.countUnread(company.id, category.kind) > 0 }"
            >{{ store.countUnread(company.id, category.kind)
            }}<span class="sr-only">건 미확인</span></span
          >
        </RouterLink>
      </div>
      <div class="company-bottom">
        <span
          ><Clock3 :size="13" />{{
            latest(company.id) ? '최근 업데이트 ' + date(latest(company.id)) : '등록된 자료 없음'
          }}</span
        ><StatusPill v-if="running(company.id)" :status="running(company.id)!.status" /><RouterLink
          v-else
          :to="`/companies/${company.id}`"
          :aria-label="`${company.name} 자료 확인`"
          >자료 확인 <ArrowRight :size="14"
        /></RouterLink>
      </div>
    </article>
  </div>
  <EmptyState
    v-else
    title="등록된 기업이 없습니다"
    message="기업 자료가 준비되면 이곳에서 업데이트를 확인할 수 있습니다."
  />
  <div class="quiet-notice">
    <span class="notice-dot" />
    <p>
      지금은 <strong>샘플 기업 목록과 두 가지 분석 사례로 구성한 워크스페이스</strong>입니다. 배지의
      읽음 상태는 유지되며, 새로고침하면 업로드·분석 자료는 초기 샘플로 돌아갑니다.
    </p>
  </div>
</template>
