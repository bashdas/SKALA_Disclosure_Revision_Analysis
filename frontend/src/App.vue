<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { LoaderCircle, RefreshCw, Sun, Moon } from 'lucide-vue-next'
import { useWorkspace } from './stores/workspace'
import { useTheme } from './stores/theme'
import { hasSession, restoreSession, logout } from './services/http'
import DocumentDrawer from './components/DocumentDrawer.vue'
const store = useWorkspace(),
  route = useRoute(),
  theme = useTheme()
const router = useRouter(),
  checking = ref(true),
  sessionError = ref('')
function signOut() {
  logout()
  window.location.assign('/login')
}
function expired() {
  store.dispose()
  window.location.assign('/login')
}
onMounted(async () => {
  window.addEventListener('session-expired', expired)
  try {
    await restoreSession()
  } catch (e) {
    sessionError.value = e instanceof Error ? e.message : '인증 확인 실패'
  } finally {
    checking.value = false
  }
  if (!hasSession()) await router.replace('/login')
  else if (route.path === '/login') await router.replace('/home')
  if (hasSession()) await store.initialize()
})
watch(
  () => route.path,
  async (path) => {
    if (checking.value) return
    if (!hasSession() && path !== '/login') await router.replace('/login')
    else if (hasSession() && path !== '/login') await store.initialize()
  },
)
onBeforeUnmount(() => {
  window.removeEventListener('session-expired', expired)
  store.dispose()
})
</script>
<template>
  <a href="#main-content" class="skip-link">본문으로 이동</a>
  <div class="app-shell">
    <div class="main-shell">
      <header class="topbar">
        <RouterLink to="/home" class="brand" aria-label="공시체크 홈"> 공시체크 </RouterLink>
        <nav class="topnav" aria-label="주 메뉴">
          <RouterLink to="/home" :class="{ active: route.path === '/home' }">내 페이지</RouterLink>
          <RouterLink to="/companies" :class="{ active: route.path.startsWith('/companies') }"
            >기업 목록</RouterLink
          >
        </nav>
        <RouterLink v-if="hasSession()" to="/account" class="text-button">내 계정</RouterLink>
        <button v-if="hasSession()" class="text-button" @click="signOut">로그아웃</button>
        <button
          class="icon-button theme-toggle"
          :aria-label="theme.theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'"
          :aria-pressed="theme.theme === 'dark'"
          :title="theme.theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'"
          @click="theme.toggle"
        >
          <Sun v-if="theme.theme === 'dark'" :size="18" />
          <Moon v-else :size="18" />
        </button>
      </header>
      <main
        id="main-content"
        tabindex="-1"
        :class="{
          'companies-main': route.path === '/companies',
          'company-main': typeof route.params.companyId === 'string',
        }"
      >
        <div v-if="checking" class="loading-state" role="status">로그인 확인 중입니다.</div>
        <RouterView v-else-if="route.path === '/login'" />
        <div v-else-if="sessionError" class="empty-state" role="alert">
          <p>{{ sessionError }}</p>
          <button class="button secondary" @click="signOut">다시 로그인</button>
        </div>
        <div v-else-if="store.loading" class="loading-state" role="status">
          <LoaderCircle :size="28" class="spin" />
          <h2>리서치 자료를 준비하고 있어요</h2>
          <p>서버의 공시와 메모를 불러옵니다.</p>
        </div>
        <div v-else-if="store.error" class="empty-state" role="alert">
          <h2>자료를 불러오지 못했어요</h2>
          <p>{{ store.error }}</p>
          <button class="button primary" @click="store.initialize">
            <RefreshCw :size="16" /> 다시 시도
          </button>
        </div>
        <template v-else-if="store.ready"
          ><p v-if="store.syncError" role="alert" class="inline-warning">{{ store.syncError }}</p>
          <RouterView
        /></template>
      </main>
    </div>
  </div>
  <DocumentDrawer />
</template>
