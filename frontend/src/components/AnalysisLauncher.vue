<script setup lang="ts">
import { notifyError } from '../lib/notifications'
import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Sparkles, ArrowRight, X } from 'lucide-vue-next'
import UiSelect from './UiSelect.vue'
import SkeletonState from './SkeletonState.vue'
import { useWorkspace } from '../stores/workspace'
import { registerDisclosure } from '../services/catalog'
import type { Filing } from '../types/domain'

const props = defineProps<{ companyId: string; filing: Filing | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useWorkspace(),
  router = useRouter()
const dialog = ref<HTMLDialogElement | null>(null)
const memoId = ref(''),
  memoVersion = ref(1),
  error = ref(''),
  pending = ref(false)
const availableMemos = computed(() => store.memosForCompany(props.companyId))
const memo = computed(() => availableMemos.value.find((m) => m.id === memoId.value))
let priorFocus: HTMLElement | null = null
let returnReceipt: string | null | undefined
function restoreTriggerFocus() {
  requestAnimationFrame(() => {
    if (dialog.value?.open) return
    const target = [...document.querySelectorAll<HTMLElement>('[data-analysis-receipt]')].find(el => el.dataset.analysisReceipt === returnReceipt) ?? priorFocus
    target?.focus()
  })
}
function close() {
  if (pending.value) return
  returnReceipt = props.filing?.receiptNo
  dialog.value?.close()
  emit('close')
}
watch(
  () => props.filing,
  async (filing) => {
    error.value = ''
    memoId.value = ''
    await nextTick()
    if (filing && dialog.value && !dialog.value.open) {
      priorFocus = document.activeElement as HTMLElement
      dialog.value.showModal()
    } else if (!filing && dialog.value?.open) dialog.value.close()
  },
  { flush: 'post' },
)
watch(
  () => props.companyId,
  () => {
    memoId.value = ''
    memoVersion.value = 1
  },
)
watch(memoId, () => {
  memoVersion.value = memo.value?.currentVersion ?? 1
})
onBeforeUnmount(() => {
  if (dialog.value?.open) dialog.value.close()
})
async function start() {
  const filing = props.filing,
    selectedMemo = memo.value,
    version = memoVersion.value
  if (!filing?.receiptNo || !selectedMemo || pending.value || store.busy)
    return
  pending.value = true
  error.value = ''
  try {
    let filingId = store.filings.find(
      (f) => f.receiptNo === filing.receiptNo && f.companyId === props.companyId,
    )?.id
    if (!filingId) {
      filingId = (await registerDisclosure(filing.receiptNo)).id
      await store.refresh()
    }
    const task = await store.start({ filingId, memoId: selectedMemo.id, memoVersion: version })
    if (task) {
      dialog.value?.close()
      emit('close')
      await router.push(`/analyses/${task.id}`)
    }
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '분석을 시작하지 못했습니다.'
  } finally {
    pending.value = false
  }
}
</script>
<template>
  <dialog
    ref="dialog"
    class="analysis-dialog analysis-launcher"
    aria-labelledby="analysis-dialog-title"
    @cancel.prevent="close"
    @close="restoreTriggerFocus"
  >
    <div class="analysis-dialog-heading">
      <h2 id="analysis-dialog-title">공시 분석</h2>
      <button
        class="icon-button"
        type="button"
        aria-label="공시 분석 닫기"
        :disabled="pending"
        @click="close"
      >
        <X :size="20" />
      </button>
    </div>
    <p class="analysis-target">{{ filing?.title }}</p>
    <SkeletonState v-if="pending" variant="analysis-form" />
    <form v-show="!pending" @submit.prevent="start">
      <div class="analysis-field">
        <span>기준 메모</span
        ><UiSelect
          v-model="memoId"
          aria-label="기준 메모"
          placeholder="메모를 선택하세요"
          :disabled="pending"
          :options="availableMemos.map((item) => ({ value: item.id, label: item.title }))"
        />
      </div>
      <p v-if="!availableMemos.length" class="small muted">선택할 메모가 없습니다.</p>
      <div v-if="memo" class="analysis-field">
        <span>기준 버전</span
        ><UiSelect
          v-model="memoVersion"
          aria-label="기준 버전"
          :disabled="pending"
          :options="
            memo.versions.map((v) => ({
              value: v.version,
              label: `v${v.version}${v.version === memo?.currentVersion ? ' , 최신 버전' : ''}`,
            }))
          "
        />
      </div>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <button
        class="button primary full-width"
        :disabled="!filing || !memo || pending || store.busy"
        type="submit"
      >
        <Sparkles :size="16" />{{ pending ? '분석 접수 중…' : '분석 시작'
        }}<ArrowRight :size="16" />
      </button>
    </form>
  </dialog>
</template>
<style scoped>
.analysis-dialog {
  width: min(520px, calc(100vw - 32px));
  max-height: calc(100dvh - 40px);
  margin: auto;
  padding: 24px;
  color: var(--ink);
  background: var(--card);
  overflow-y: auto;
  overscroll-behavior: none;
}
.analysis-dialog::backdrop {
  background: rgb(0 0 0 / 55%);
}
.analysis-dialog-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.analysis-dialog-heading h2 {
  margin: 0;
}
.analysis-target {
  margin-top: 16px;
  color: var(--secondary);
  overflow-wrap: anywhere;
}
.analysis-dialog form {
  display: block;
  margin-top: 20px;
}
.analysis-dialog .analysis-field {
  display: block;
  margin-bottom: 20px;
}
.analysis-dialog form > .button {
  margin-top: 20px;
}
</style>
