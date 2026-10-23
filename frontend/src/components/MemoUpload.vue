<script setup lang="ts">
import { toast, notifyError } from '../lib/notifications'
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { Upload, FileText, Pencil, Plus, X } from 'lucide-vue-next'
import SkeletonState from './SkeletonState.vue'
import { useWorkspace } from '../stores/workspace'
const props = defineProps<{ companyId: string; companyName: string }>()
const store = useWorkspace()
const dialog = ref<HTMLDialogElement | null>(null)
function close() {
  if (!uploading.value) dialog.value?.close()
}
async function tabKey(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || uploading.value) return
  event.preventDefault()
  setMode(event.key === 'Home' ? false : event.key === 'End' ? true : !writing.value)
  await nextTick()
  dialog.value?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')?.focus()
}
onBeforeUnmount(() => {
  if (dialog.value?.open) dialog.value.close()
})
const writing = ref(false),
  content = ref('')
const title = ref(''),
  file = ref<File | null>(null),
  fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false),
  error = ref('')
function setMode(value: boolean) {
  writing.value = value
  error.value = ''
}
function select(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''
}
async function upload() {
  if (uploading.value || (writing.value ? !content.value.trim() : !file.value)) return
  error.value = ''
  uploading.value = true
  try {
    const memo = await store.upload(
      writing.value ? new File([content.value], 'memo.txt', { type: 'text/plain' }) : file.value!,
      title.value.trim() ? title.value : writing.value ? `${props.companyName} 메모` : undefined,
      props.companyId,
    )
    toast.success('메모를 추가했습니다.', { description: memo.title })
    file.value = null
    title.value = ''
    content.value = ''
    if (fileInput.value) fileInput.value.value = ''
    dialog.value?.close()
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '메모를 추가하지 못했습니다.'
  } finally {
    uploading.value = false
  }
}
</script>
<template>
  <button class="button primary" type="button" @click="dialog?.showModal()">
    <Plus :size="16" />메모 추가
  </button>
  <dialog
    ref="dialog"
    class="memo-dialog surface upload-panel"
    :aria-labelledby="'memo-title-' + companyId"
    @cancel.prevent="close"
  >
    <div class="memo-dialog-heading">
      <h2 :id="'memo-title-' + companyId">메모 추가</h2>
      <button
        class="icon-button"
        type="button"
        aria-label="메모 추가 닫기"
        :disabled="uploading"
        @click="close"
      >
        <X :size="20" />
      </button>
    </div>
    <div class="memo-mode-tabs" role="tablist" aria-label="메모 추가 방식" @keydown="tabKey">
      <button
        class="button secondary"
        type="button"
        role="tab"
        :id="'memo-upload-tab-' + companyId"
        :aria-controls="'memo-editor-' + companyId"
        :aria-selected="!writing"
        :tabindex="!writing ? 0 : -1"
        :disabled="uploading"
        @click="setMode(false)"
      >
        파일 업로드
      </button>
      <button
        class="button secondary"
        type="button"
        role="tab"
        :id="'memo-write-tab-' + companyId"
        :aria-controls="'memo-editor-' + companyId"
        :aria-selected="writing"
        :tabindex="writing ? 0 : -1"
        :disabled="uploading"
        @click="setMode(true)"
      >
        작성
      </button>
    </div>
    <SkeletonState v-if="uploading" :variant="writing ? 'memo-write' : 'memo-upload'" />
    <form
      v-show="!uploading"
      :id="'memo-editor-' + companyId"
      role="tabpanel"
      :aria-labelledby="(writing ? 'memo-write-tab-' : 'memo-upload-tab-') + companyId"
      @submit.prevent="upload"
    >
      <label v-if="!writing" class="file-zone"
        ><FileText :size="25" /><strong>{{ file?.name ?? '텍스트 파일 선택' }}</strong
        ><span>.txt , UTF-8 , 최대 5 MiB</span
        ><input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          aria-label="메모 파일"
          :disabled="uploading"
          @change="select"
      /></label>
      <label
        >메모 제목 <span class="muted">(선택)</span
        ><input
          v-model="title"
          :disabled="uploading"
          maxlength="500"
          :placeholder="writing ? '메모 제목을 입력하세요' : '비워 두면 파일명을 사용합니다'"
      /></label>
      <label v-if="writing"
        >메모 내용<textarea
          v-model="content"
          rows="12"
          required
          :disabled="uploading"
          placeholder="분석의 기준이 될 메모를 작성하세요."
        ></textarea>
      </label>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <button
        class="button primary full-width"
        type="submit"
        :disabled="uploading || (writing ? !content.trim() : !file)"
      >
        <Pencil v-if="writing" :size="16" /><Upload v-else :size="16" />{{
          uploading ? '저장 중…' : writing ? '저장' : '메모 업로드'
        }}
      </button>
    </form>
  </dialog>
</template>
<style scoped>
.memo-dialog {
  width: min(600px, calc(100vw - 32px));
  max-height: calc(100dvh - 40px);
  margin: auto;
  padding: 24px;
  color: var(--ink);
  overflow-y: auto;
  overscroll-behavior: none;
}
.memo-dialog::backdrop {
  background: rgb(0 0 0 / 55%);
}
.memo-dialog-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.memo-dialog-heading h2 {
  margin: 0;
}
.memo-mode-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}
.memo-mode-tabs button {
  flex: 1;
  border-radius: 8px;
}

textarea {
  display: block;
  width: 100%;
  margin-top: 7px;
  height: 240px;
  min-height: 220px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-strong);
  color: var(--ink);
  font-weight: 400;
  line-height: 1.7;
  resize: vertical;
}
textarea:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 4px;
}
.memo-mode-tabs button[aria-selected='true'] {
  background: var(--primary-soft);
  color: var(--primary);
}
</style>
