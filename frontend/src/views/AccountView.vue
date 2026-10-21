<script setup lang="ts">
import { ref } from 'vue'
import { currentUser, changePassword } from '../services/http'
const currentPassword = ref(''), newPassword = ref(''), confirmPassword = ref('')
const busy = ref(false), error = ref('')
async function submit() {
  error.value = ''
  if (newPassword.value !== confirmPassword.value) { error.value = '새 비밀번호가 일치하지 않습니다.'; return }
  if (busy.value) return
  busy.value = true
  try {
    await changePassword(currentPassword.value, newPassword.value)
    window.location.assign('/login')
  } catch (e) { error.value = e instanceof Error ? e.message : '비밀번호 변경 실패' }
  finally { busy.value = false }
}
</script>
<template>
  <section class="surface demo-login">
    <h1>내 계정</h1>
    <p>{{ currentUser?.email }}</p>
    <p class="small muted">권한: {{ currentUser?.role }}</p>
    <h2>비밀번호 변경</h2>
    <form @submit.prevent="submit">
      <label>현재 비밀번호<input v-model="currentPassword" type="password" autocomplete="current-password" required maxlength="1024" /></label>
      <label>새 비밀번호<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label>
      <label>새 비밀번호 확인<input v-model="confirmPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label>
      <p class="small muted">비밀번호는 12~128자입니다. 변경하면 기존 로그인 세션이 만료됩니다.</p>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <button class="button primary full-width" type="submit" :disabled="busy">{{ busy ? '변경 중…' : '비밀번호 변경' }}</button>
    </form>
  </section>
</template>
