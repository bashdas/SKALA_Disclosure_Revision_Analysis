<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Sparkles, ArrowRight, LockKeyhole } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import type { Scenario } from '../types/domain'
const props = defineProps<{ companyId: string; preferredFiling?: string }>()
const store = useWorkspace(),
  router = useRouter(),
  route = useRoute()
const filingId = ref(''),
  memoId = ref(''),
  memoVersion = ref(1),
  error = ref('')
const availableFilings = computed(() =>
  store.filings.filter((f) => f.companyId === props.companyId),
)
const availableMemos = computed(() =>
  store.memos.filter(
    (m) => m.companyName === store.companyName(props.companyId) || m.companyName === null,
  ),
)
const memo = computed(() => store.memos.find((m) => m.id === memoId.value))
watch(
  () => props.preferredFiling,
  (id) => {
    if (id) filingId.value = id
  },
)
watch(memoId, () => {
  memoVersion.value = memo.value?.currentVersion ?? 1
})
watch(
  () => props.companyId,
  () => {
    filingId.value = ''
    memoId.value = ''
    error.value = ''
  },
)
async function start() {
  if (!filingId.value || !memoId.value || store.busy) return
  error.value = ''
  const allowed: Scenario[] = [
    'normal',
    'evidence-gap',
    'analysis-failure',
    'save-failure',
    'limit',
  ]
  const requested = String(route.query.scenario ?? 'normal')
  try {
    const task = await store.start({
      filingId: filingId.value,
      memoId: memoId.value,
      memoVersion: memoVersion.value,
      scenario: allowed.includes(requested as Scenario) ? (requested as Scenario) : 'normal',
    })
    if (task) await router.push(`/analyses/${task.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '분석을 시작하지 못했습니다.'
  }
}
</script>
<template>
  <aside class="analysis-launcher">
    <span class="launcher-icon"><Sparkles :size="21" /></span>
    <h2>공시 체크</h2>
    <p class="muted small">공시와 기준 메모를 선택하면 재검토가 필요한 논리를 살펴봅니다.</p>
    <form @submit.prevent="start">
      <label
        >대상 공시<select v-model="filingId" aria-label="대상 공시" required>
          <option value="" disabled>공시를 선택하세요</option>
          <option v-for="filing in availableFilings" :key="filing.id" :value="filing.id">
            {{ filing.title }}
          </option>
        </select></label
      >
      <label
        >기준 메모<select v-model="memoId" aria-label="기준 메모" required>
          <option value="" disabled>메모를 선택하세요</option>
          <option v-for="item in availableMemos" :key="item.id" :value="item.id">
            {{ item.title }}{{ item.companyName ? '' : ' · 기업 미확정' }}
          </option>
        </select></label
      >
      <label v-if="memo"
        >기준 버전<select v-model.number="memoVersion" aria-label="기준 버전">
          <option v-for="v in memo.versions" :key="v.version" :value="v.version">
            v{{ v.version }}{{ v.version === memo.currentVersion ? ' · 최신 버전' : '' }}
          </option>
        </select></label
      >
      <p v-if="memo?.companyName === null" class="inline-warning">
        기업 미확정 메모입니다. 선택한 공시와 관련 있는지 확인하세요.
      </p>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <button
        class="button primary full-width"
        :disabled="!filingId || !memoId || store.busy"
        type="submit"
      >
        <Sparkles :size="16" />{{ store.busy ? '분석 접수 중…' : '영향 분석 시작'
        }}<ArrowRight :size="16" />
      </button>
    </form>
    <div class="preserve-note">
      <LockKeyhole :size="14" /><span>원본 메모는 변경되지 않습니다.</span>
    </div>
    <p class="tiny muted">샘플 분석 · 실제 AI·외부 API 호출 없음</p>
  </aside>
</template>
