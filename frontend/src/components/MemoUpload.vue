<script setup lang="ts">
import { ref } from 'vue'
import { Upload, FileText, CheckCircle2, Pencil } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
const props = defineProps<{ companyId: string; companyName: string }>()
const store = useWorkspace()
const writing = ref(false),
  content = ref('')
const title = ref(''),
  file = ref<File | null>(null),
  fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false),
  error = ref(''),
  success = ref('')
function setMode(value: boolean) {
  writing.value = value
  error.value = ''
  success.value = ''
}
function select(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''
  success.value = ''
}
async function upload() {
  if (uploading.value || (writing.value ? !content.value.trim() : !file.value)) return
  error.value = ''
  success.value = ''
  uploading.value = true
  try {
    const memo = await store.upload(
      writing.value ? new File([content.value], 'memo.txt', { type: 'text/plain' }) : file.value!,
      title.value.trim() ? title.value : writing.value ? `${props.companyName} 메모` : undefined,
      props.companyId,
    )
    success.value = `‘${memo.title}’ 메모를 ${memo.companyName ?? props.companyName}에 추가했습니다. v1`
    file.value = null
    title.value = ''
    content.value = ''
    if (fileInput.value) fileInput.value.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '메모를 추가하지 못했습니다.'
  } finally {
    uploading.value = false
  }
}
</script>
<template>
  <aside class="surface upload-panel">
    <span class="launcher-icon"><Upload :size="21" /></span>
    <h2>기준 메모 추가</h2>
    <p class="small muted">{{ companyName }}의 기준 메모를 추가하세요.</p>
    <div class="row-actions">
      <button
        class="button secondary"
        type="button"
        :aria-pressed="!writing"
        :disabled="uploading"
        @click="setMode(false)"
      >
        파일 업로드
      </button>
      <button
        class="button secondary"
        type="button"
        :aria-pressed="writing"
        :disabled="uploading"
        @click="setMode(true)"
      >
        작성
      </button>
    </div>
    <form @submit.prevent="upload">
      <label v-if="!writing" class="file-zone"
        ><FileText :size="25" /><strong>{{ file?.name ?? '텍스트 파일 선택' }}</strong
        ><span>.txt , UTF-8 , 최대 5 MiB</span
        ><input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          aria-label="메모 파일"
          @change="select"
      /></label>
      <label
        >메모 제목 <span class="muted">(선택)</span
        ><input
          v-model="title"
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
      <p v-if="success" role="status" class="success-message">
        <CheckCircle2 :size="16" />{{ success }}
      </p>
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
    <p class="tiny muted">
      {{ companyName }}의 메모로 서버에 저장합니다. 이 기업의 메모 목록과 분석 선택란에서 확인할 수
      있습니다.
    </p>
  </aside>
</template>
<style scoped>
textarea {
  display: block;
  width: 100%;
  margin-top: 7px;
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
.row-actions button[aria-pressed='true'] {
  background: var(--primary-soft);
  color: var(--primary);
}
</style>
