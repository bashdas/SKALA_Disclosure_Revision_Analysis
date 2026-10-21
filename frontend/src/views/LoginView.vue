<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, UserRound } from 'lucide-vue-next'
import { demoUsers, usePreferences } from '../stores/preferences'
const preferences = usePreferences(),
  router = useRouter()
const selectedUser = ref(preferences.activeUserId)
function signIn() {
  preferences.selectUser(selectedUser.value)
  router.push('/home')
}
</script>
<template>
  <section class="surface demo-login">
    <span class="launcher-icon"><UserRound :size="24" /></span>
    <h1>내 리서치 시작하기</h1>
    <p class="muted">데모 사용자를 선택해 개인 홈을 확인하세요.</p>
    <form @submit.prevent="signIn">
      <label for="login-user">데모 사용자</label
      ><select id="login-user" v-model="selectedUser">
        <option v-for="user in demoUsers" :key="user.id" :value="user.id">
          {{ user.name }} · {{ user.field }}
        </option></select
      ><button class="button primary full-width" type="submit">
        데모 로그인 <ArrowRight :size="16" />
      </button>
    </form>
    <p class="tiny muted">
      실제 계정 인증이 없는 UI 시연입니다. 선택하면 해당 사용자의 담당 분야와 관심종목이 있는 홈으로
      이동합니다.
    </p>
  </section>
</template>
