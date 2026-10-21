<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { useWorkspace } from './stores/workspace'
import DocumentDrawer from './components/DocumentDrawer.vue'
const store = useWorkspace(),
  route = useRoute()
onMounted(() => store.initialize())
</script>
<template>
  <a href="#main-content" class="skip-link">본문으로 이동</a>
  <div class="app-shell">
    <div class="main-shell">
      <header class="topbar">
        <RouterLink to="/home" class="brand" aria-label="공시체크 홈"> 공시체크 </RouterLink>
        <nav class="topnav" aria-label="주 메뉴">
          <RouterLink to="/home" :class="{ active: route.path === '/home' }">홈</RouterLink>
          <RouterLink to="/companies" :class="{ active: route.path.startsWith('/companies') }"
            >기업 목록</RouterLink
          >
        </nav>
      </header>
      <main
        id="main-content"
        tabindex="-1"
        :class="{ 'companies-main': route.path === '/companies' }"
      >
        <div v-if="store.loading" class="loading-state" role="status">
          <LoaderCircle :size="28" class="spin" />
          <h2>리서치 자료를 준비하고 있어요</h2>
          <p>샘플 공시와 메모를 불러옵니다.</p>
        </div>
        <div v-else-if="store.error" class="empty-state" role="alert">
          <h2>자료를 불러오지 못했어요</h2>
          <p>{{ store.error }}</p>
          <button class="button primary" @click="store.initialize">
            <RefreshCw :size="16" /> 다시 시도
          </button>
        </div>
        <RouterView v-else-if="store.ready" />
      </main>
      <footer class="app-footer">
        <span>공시체크 · 리서치 의사결정 지원</span
        ><span>시연용 데이터 · 최종 판단은 리서처가 수행합니다.</span>
      </footer>
    </div>
  </div>
  <DocumentDrawer />
</template>
