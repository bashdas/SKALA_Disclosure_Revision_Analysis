<script setup lang="ts">
import { toast, notifyError } from '../lib/notifications'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import SkeletonState from '../components/SkeletonState.vue'
import { login, signup } from '../services/http'
const router = useRouter()
const registering = ref(false),
  organizationName = ref(''),
  notice = ref('')
const email = ref(''),
  password = ref(''),
  busy = ref(false),
  error = ref('')
function toggleMode() {
  registering.value = !registering.value
  error.value = ''
  notice.value = ''
  password.value = ''
}
async function signIn() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (registering.value) {
      await signup(email.value, password.value, organizationName.value)
      registering.value = false
      password.value = ''
      notice.value = '회원가입을 완료했습니다. 비밀번호를 입력해 로그인하세요.'
      toast.success(notice.value)
      return
    }
    await login(email.value, password.value)
    password.value = ''
    toast.success('로그인했습니다.')
    await router.replace('/home')
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '로그인에 실패했습니다.'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <section class="surface demo-login">
    <h1>{{ registering ? '공시체크 회원가입' : '공시체크 로그인' }}</h1>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="registering" class="small muted">가입하면 새 조직이 생성됩니다.</p>
    <SkeletonState v-if="busy" variant="login-form" :rows="registering ? 3 : 2" />
    <form v-show="!busy" @submit.prevent="signIn">
      <label v-if="registering"
        >조직 이름<input
          v-model="organizationName"
          required
          maxlength="255"
          autocomplete="organization"
      /></label>
      <label
        >이메일<input v-model="email" type="email" autocomplete="username" required maxlength="320"
      /></label>
      <label
        >비밀번호<input
          v-model="password"
          type="password"
          :autocomplete="registering ? 'new-password' : 'current-password'"
          :minlength="registering ? 12 : 1"
          required
          :maxlength="registering ? 128 : 1024"
      /></label>
      <p v-if="error" class="field-error" role="alert">{{ error }}</p>
      <button class="button primary full-width" :disabled="busy" type="submit">
        {{ busy ? '처리 중…' : registering ? '회원가입' : '로그인' }}
      </button>
    </form>
    <button class="text-button" :disabled="busy" @click="toggleMode">
      {{ registering ? '로그인으로 이동' : '회원가입' }}
    </button>
  </section>
</template>
