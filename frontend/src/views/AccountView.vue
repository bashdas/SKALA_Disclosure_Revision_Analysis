<script setup lang="ts">
import { toast, notifyError, queueNotice } from '../lib/notifications'
import { ref, nextTick, watch, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import SkeletonState from '../components/SkeletonState.vue'
import { currentUser, changePassword, changeName, deleteAccount, logout } from '../services/http'
import { useTheme } from '../stores/theme'
const theme = useTheme()
const name = ref(''),
  deletePassword = ref(''),
  confirmingDelete = ref(false)
const dialog = ref<HTMLDialogElement | null>(null)
const route = useRoute(),
  router = useRouter()
function open() {
  name.value = currentUser.value?.name ?? ''
  dialog.value?.showModal()
}
function close() {
  if (busy.value) return
  dialog.value?.close()
  currentPassword.value = newPassword.value = confirmPassword.value = ''
  error.value = ''
  deletePassword.value = ''
  confirmingDelete.value = false
  if (route.query.account === 'open') {
    const { account, ...query } = route.query
    void router.replace({ query })
  }
}
watch(
  () => route.query.account,
  async (value) => {
    if (value === 'open') {
      await nextTick()
      if (!dialog.value?.open) open()
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (dialog.value?.open) dialog.value.close()
})
const currentPassword = ref(''),
  newPassword = ref(''),
  confirmPassword = ref('')
const busy = ref(false),
  error = ref('')
async function submit() {
  error.value = ''
  if (newPassword.value !== confirmPassword.value) {
    error.value = '새 비밀번호가 일치하지 않습니다.'
    notifyError(error.value)
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    await changePassword(currentPassword.value, newPassword.value)
    queueNotice('비밀번호를 변경했습니다. 다시 로그인해 주세요.')
    window.location.assign('/login')
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '비밀번호 변경 실패'
  } finally {
    busy.value = false
  }
}
function signOut() {
  logout()
  window.location.assign('/login')
}
async function saveName() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await changeName(name.value.trim())
    toast.success('이름을 변경했습니다.')
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '이름 변경 실패'
  } finally {
    busy.value = false
  }
}
async function withdraw() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await deleteAccount(deletePassword.value)
    queueNotice('계정 탈퇴를 완료했습니다.')
    window.location.assign('/login')
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '계정 탈퇴 실패'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <button class="text-button account-name" type="button" aria-haspopup="dialog" @click="open">
    {{ currentUser?.name || currentUser?.email.split('@')[0] }}
  </button>
  <dialog
    ref="dialog"
    class="account-dialog surface"
    aria-labelledby="account-title"
    @cancel.prevent="close"
  >
    <div class="account-dialog-heading">
      <h2 id="account-title">설정</h2>
      <button
        class="icon-button"
        type="button"
        aria-label="내 계정 닫기"
        :disabled="busy"
        @click="close"
      >
        <X :size="20" />
      </button>
    </div>
    <p>{{ currentUser?.email }}</p>
    <h3>이름 변경</h3>
    <form @submit.prevent="saveName">
      <label
        >이름<input
          v-model="name"
          required
          maxlength="100"
          autocomplete="name"
          pattern=".*\S.*"
          :disabled="busy"
      /></label>
      <button class="button secondary full-width" type="submit" :disabled="busy">이름 저장</button>
    </form>
    <h3>비밀번호 변경</h3>
    <SkeletonState v-if="busy || !currentUser" variant="account-form" />
    <form v-show="!busy && currentUser" aria-label="비밀번호 변경" @submit.prevent="submit">
      <label
        >현재 비밀번호<input
          v-model="currentPassword"
          :disabled="busy"
          type="password"
          autocomplete="current-password"
          required
          maxlength="1024"
      /></label>
      <label
        >새 비밀번호<input
          v-model="newPassword"
          :disabled="busy"
          type="password"
          autocomplete="new-password"
          required
          minlength="12"
          maxlength="128"
      /></label>
      <label
        >새 비밀번호 확인<input
          v-model="confirmPassword"
          :disabled="busy"
          type="password"
          autocomplete="new-password"
          required
          minlength="12"
          maxlength="128"
      /></label>
      <p class="small muted">비밀번호는 12~128자입니다. 변경하면 기존 로그인 세션이 만료됩니다.</p>
      <button class="button primary full-width" type="submit" :disabled="busy">
        {{ busy ? '변경 중…' : '비밀번호 변경' }}
      </button>
    </form>
    <p v-if="error" role="alert" class="field-error">{{ error }}</p>
    <h3>화면</h3>
    <button
      class="button secondary full-width"
      type="button"
      :aria-pressed="theme.theme === 'dark'"
      @click="theme.toggle"
    >
      {{ theme.theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환' }}
    </button>
    <h3>계정</h3>
    <div class="account-actions">
      <button class="button secondary" type="button" :disabled="busy" @click="signOut">
        로그아웃
      </button>
      <button
        class="button secondary"
        type="button"
        :disabled="busy"
        @click="confirmingDelete = !confirmingDelete"
      >
        계정 탈퇴
      </button>
    </div>
    <form
      v-if="confirmingDelete"
      class="withdraw-form"
      aria-label="계정 탈퇴 확인"
      @submit.prevent="withdraw"
    >
      <p>탈퇴하면 로그인할 수 없으며 이름과 이메일이 삭제됩니다. 작성한 조직 자료는 보존됩니다.</p>
      <label
        >현재 비밀번호<input
          v-model="deletePassword"
          type="password"
          autocomplete="current-password"
          required
          maxlength="1024"
          :disabled="busy"
      /></label>
      <button class="button secondary full-width" type="submit" :disabled="busy">탈퇴 확정</button>
    </form>
  </dialog>
</template>

<style scoped>
.account-dialog {
  width: min(480px, calc(100vw - 32px));
  max-height: calc(100dvh - 40px);
  margin: auto;
  padding: 24px;
  color: var(--ink);
  overflow-y: auto;
  overscroll-behavior: none;
}
.account-dialog::backdrop {
  background: rgb(0 0 0 / 55%);
}
.account-dialog-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.account-dialog h3 {
  margin: 24px 0 16px;
}
.account-dialog label {
  display: block;
  margin-bottom: 16px;
}
.account-dialog form > .button {
  margin-top: 20px;
}
.account-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.withdraw-form {
  margin-top: 20px;
}
.withdraw-form p {
  margin-bottom: 16px;
}
</style>
