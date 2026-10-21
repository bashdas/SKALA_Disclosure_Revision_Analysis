<script setup lang="ts">
import { ref } from 'vue'
import { Upload, FileText, CheckCircle2 } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
const props = defineProps<{ companyId: string; companyName: string }>()
const store = useWorkspace()
const title = ref(''),
  file = ref<File | null>(null),
  fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false),
  error = ref(''),
  success = ref('')
function select(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''
  success.value = ''
}
async function upload() {
  if (!file.value || uploading.value) return
  error.value = ''
  success.value = ''
  uploading.value = true
  try {
    const memo = await store.upload(
      file.value,
      title.value.trim() ? title.value : undefined,
      props.companyId,
    )
    success.value = `‘${memo.title}’ 메모를 추가했습니다. ${props.companyName} · v1`
    file.value = null
    title.value = ''
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
    <p class="small muted">{{ companyName }}의 UTF-8 텍스트 메모를 등록하세요.</p>
    <form @submit.prevent="upload">
      <label class="file-zone"
        ><FileText :size="25" /><strong>{{ file?.name ?? '텍스트 파일 선택' }}</strong
        ><span>.txt · UTF-8 · 최대 5 MiB</span
        ><input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          aria-label="메모 파일"
          @change="select"
      /></label>
      <label
        >메모 제목 <span class="muted">(선택)</span
        ><input v-model="title" maxlength="500" placeholder="비워 두면 파일명을 사용합니다"
      /></label>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <p v-if="success" role="status" class="success-message">
        <CheckCircle2 :size="16" />{{ success }}
      </p>
      <button class="button primary full-width" type="submit" :disabled="!file || uploading">
        <Upload :size="16" />{{ uploading ? '추가 중…' : '메모 업로드' }}
      </button>
    </form>
    <p class="tiny muted">
      이 종목의 메모로 등록됩니다. 샘플 업로드 자료는 새로고침하면 사라지며 실제 서버에는 저장되지
      않습니다.
    </p>
  </aside>
</template>
