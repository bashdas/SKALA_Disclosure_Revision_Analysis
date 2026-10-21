<script setup lang="ts">
import { useWorkspace } from '../stores/workspace'
import EmptyState from '../components/EmptyState.vue'
import CompanyQuotesTable from '../components/CompanyQuotesTable.vue'
const store = useWorkspace()
</script>
<template>
  <div class="section-heading">
    <h1 class="company-list-title">
      리서치 기업 <span class="count">{{ store.companies.length }}</span>
    </h1>
    <span class="muted small">시세 예시 · 업데이트 배지를 눌러 새 자료를 확인하세요</span>
  </div>
  <section
    v-if="store.companies.length"
    class="surface company-directory"
    aria-label="리서치 기업 목록"
  >
    <CompanyQuotesTable :companies="store.companies" directory />
  </section>
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
