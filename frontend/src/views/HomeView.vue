<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useWorkspace } from '../stores/workspace'
import { currentUser } from '../services/http'
import EmptyState from '../components/EmptyState.vue'
import MarketStrip from '../components/MarketStrip.vue'
import CompanyQuotesTable from '../components/CompanyQuotesTable.vue'
const store = useWorkspace()
const favorites = computed(() => store.companies.filter((c) => c.favorite))
</script>
<template>
  <section class="home-heading">
    <div>
      <h1>{{ currentUser?.email.split('@')[0] }}님의 리서치 홈</h1>
    </div>
  </section>
  <MarketStrip />
  <div class="home-layout">
    <section class="surface watchlist" aria-labelledby="watchlist-heading">
      <div class="list-heading">
        <h2 id="watchlist-heading">
          내 관심종목 <span class="count">{{ favorites.length }}</span>
        </h2>
      </div>
      <CompanyQuotesTable :companies="favorites" />
      <EmptyState
        v-if="!favorites.length"
        title="관심종목을 추가해 보세요"
        message="기업 목록에서 별을 누르면 내 홈에 모아볼 수 있습니다."
        ><RouterLink to="/companies" class="button secondary"
          >기업 목록 보기</RouterLink
        ></EmptyState
      >
    </section>
  </div>
</template>
