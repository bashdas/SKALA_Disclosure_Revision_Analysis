<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Sparkles, ArrowRight } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
const props = defineProps<{ companyId: string; preferredFiling?: string }>()
const store = useWorkspace(),
  router = useRouter()
const filingId = ref(''),
  memoId = ref(''),
  memoVersion = ref(1),
  error = ref('')
const availableFilings = computed(() =>
  store.filings.filter((f) => f.companyId === props.companyId && f.isCorrection),
)
const availableMemos = computed(() => store.memosForCompany(props.companyId))
const memo = computed(() => availableMemos.value.find((m) => m.id === memoId.value))
watch(
  () => props.preferredFiling,
  (id) => {
    if (id) filingId.value = id
  },
  { immediate: true },
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
  if (!filingId.value || !memo.value || store.busy) return
  error.value = ''
  try {
    const task = await store.start({
      filingId: filingId.value,
      memoId: memoId.value,
      memoVersion: memoVersion.value,
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
        >대상 정정공시<select v-model="filingId" aria-label="대상 정정공시" required>
          <option value="" disabled>정정공시를 선택하세요</option>
          <option v-for="filing in availableFilings" :key="filing.id" :value="filing.id">
            {{ filing.title }}
          </option>
        </select></label
      >
      <label
        >기준 메모<select v-model="memoId" aria-label="기준 메모" required>
          <option value="" disabled>메모를 선택하세요</option>
          <option v-for="item in availableMemos" :key="item.id" :value="item.id">
            {{ item.title }}
          </option>
        </select></label
      >
      <label v-if="memo"
        >기준 버전<select v-model.number="memoVersion" aria-label="기준 버전">
          <option v-for="v in memo.versions" :key="v.version" :value="v.version">
            v{{ v.version }}{{ v.version === memo.currentVersion ? ' , 최신 버전' : '' }}
          </option>
        </select></label
      >
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <button
        class="button primary full-width"
        :disabled="!filingId || !memo || store.busy"
        type="submit"
      >
        <Sparkles :size="16" />{{ store.busy ? '분석 접수 중…' : '영향 분석 시작'
        }}<ArrowRight :size="16" />
      </button>
    </form>
  </aside>
</template>
