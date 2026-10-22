<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { RefreshCw } from 'lucide-vue-next'
import { useWorkspace } from './stores/workspace'
import { hasSession, restoreSession, logout } from './services/http'
import ToastOutlet from './components/ToastOutlet.vue'
import { notifyError } from './lib/notifications'
import SkeletonState from './components/SkeletonState.vue'
import AccountView from './views/AccountView.vue'
import DocumentDrawer from './components/DocumentDrawer.vue'
const store = useWorkspace(),
  route = useRoute()
const router = useRouter(),
  checking = ref(true),
  sessionError = ref('')
const pageSkeleton = computed(() => {
  if (route.path === '/login') return 'login'
  if (route.path === '/home' || route.path === '/') return 'home'
  if (route.params.companyId) return 'company'
  if (route.params.taskId) return 'analysis'
  return 'directory'
})
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
    notifyError(e)
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
        <AccountView v-if="hasSession()" />
      </header>
      <main
        id="main-content"
        tabindex="-1"
        :class="{
          'companies-main': route.path === '/companies',
          'company-main': typeof route.params.companyId === 'string',
        }"
      >
        <SkeletonState v-if="checking" :variant="pageSkeleton" :rows="7" header />
        <RouterView v-else-if="route.path === '/login'" />
        <div v-else-if="sessionError" class="empty-state" role="alert">
          <p>{{ sessionError }}</p>
          <button class="button secondary" @click="signOut">다시 로그인</button>
        </div>
        <SkeletonState v-else-if="store.loading" :variant="pageSkeleton" :rows="7" header />
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
  <ToastOutlet />
</template>
