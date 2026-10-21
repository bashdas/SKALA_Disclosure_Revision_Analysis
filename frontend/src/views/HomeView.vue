<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowUpRight, ArrowRight, Star, FileText, Sparkles } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { demoUsers, usePreferences } from '../stores/preferences'
import EmptyState from '../components/EmptyState.vue'
import MarketStrip from '../components/MarketStrip.vue'
const store = useWorkspace(),
  preferences = usePreferences()
const favorites = computed(() => store.companies.filter((c) => preferences.isFavorite(c.id)))
</script>
<template>
  <section class="home-heading">
    <div>
      <p class="eyebrow">MY RESEARCH</p>
      <h1>{{ preferences.user.name }}님의 리서치 홈</h1>
    </div>
    <div class="demo-user-switch">
      <label for="demo-user">데모 사용자 전환</label
      ><select
        id="demo-user"
        :value="preferences.activeUserId"
        @change="preferences.selectUser(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="user in demoUsers" :key="user.id" :value="user.id">
          {{ user.name }} · {{ user.field }}
        </option>
      </select>
    </div>
  </section>
  <MarketStrip />
  <div class="home-layout">
    <section class="surface watchlist" aria-labelledby="watchlist-heading">
      <div class="list-heading">
        <h2 id="watchlist-heading">
          내 관심종목 <span class="count">{{ favorites.length }}</span>
        </h2>
        <RouterLink to="/companies" class="text-button"
          >종목 관리 <ArrowRight :size="14"
        /></RouterLink>
      </div>
      <article
        v-for="company in favorites"
        :key="company.id"
        class="watchlist-row"
        :data-testid="`favorite-${company.id}`"
      >
        <span class="company-logo" :class="company.id">{{ company.initials }}</span>
        <div class="watchlist-company">
          <RouterLink :to="`/companies/${company.id}`"
            >{{ company.name }} <ArrowUpRight :size="14" /></RouterLink
          ><span class="small muted">{{ company.sector }} · {{ company.code }}</span>
          <div
            v-if="
              store.countUnread(company.id, 'filing') > 0 ||
              store.countUnread(company.id, 'report') > 0
            "
            class="watchlist-updates"
          >
            <RouterLink
              v-if="store.countUnread(company.id, 'filing') > 0"
              :to="`/companies/${company.id}?tab=filings`"
              ><FileText :size="12" />공시 {{ store.countUnread(company.id, 'filing') }}</RouterLink
            ><RouterLink
              v-if="store.countUnread(company.id, 'report') > 0"
              :to="`/companies/${company.id}?tab=reports`"
              ><Sparkles :size="12" />AI 보고서
              {{ store.countUnread(company.id, 'report') }}</RouterLink
            >
          </div>
        </div>
        <button
          class="favorite-button selected"
          :aria-label="`${company.name} 관심종목 해제`"
          aria-pressed="true"
          @click="preferences.toggleFavorite(company.id)"
        >
          <Star :size="19" />
        </button>
      </article>
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
  <p class="home-demo-note">
    로그인 후 홈을 미리 보는 데모입니다. 사용자별 관심종목은 이 브라우저에 저장되며, 실제
    로그인·권한 관리와 실시간 시세는 연결 전입니다.
  </p>
  <p v-if="preferences.storageNotice" class="inline-warning" role="status">
    {{ preferences.storageNotice }}
  </p>
</template>
