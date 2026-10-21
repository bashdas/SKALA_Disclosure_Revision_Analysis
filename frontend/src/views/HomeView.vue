<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useWorkspace } from '../stores/workspace'
import { currentUser } from '../services/http'
import EmptyState from '../components/EmptyState.vue'
import MarketStrip from '../components/MarketStrip.vue'
import CompanyQuotesTable from '../components/CompanyQuotesTable.vue'
const store = useWorkspace()
const search = ref('')
const favorites = computed(() => store.companies.filter((c) => c.favorite))
const filteredFavorites = computed(() => {
  const query = search.value.trim().normalize('NFC').toLocaleLowerCase('ko-KR')
  return favorites.value.filter(
    (c) =>
      c.name.normalize('NFC').toLocaleLowerCase('ko-KR').includes(query) ||
      c.code.toLowerCase().includes(query),
  )
})
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
      <div class="list-heading favorite-heading">
        <h2 id="watchlist-heading">
          내 관심종목 <span class="count">{{ favorites.length }}</span>
        </h2>
        <input
          v-model="search"
          class="compact-search"
          type="search"
          aria-label="관심종목 검색"
          placeholder="기업명 또는 종목코드 검색"
          maxlength="100"
        />
      </div>
      <CompanyQuotesTable :companies="filteredFavorites" />
      <EmptyState
        v-if="favorites.length && !filteredFavorites.length"
        title="검색 결과가 없습니다"
        message="기업명이나 종목코드를 확인해 주세요."
      />
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

<style scoped>
.favorite-heading {
  gap: 16px;
  flex-wrap: wrap;
}
.favorite-heading input {
  margin-left: auto;
  width: min(100%, 280px);
}
</style>
