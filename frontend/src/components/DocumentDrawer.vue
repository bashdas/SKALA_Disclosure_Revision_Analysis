<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X, ExternalLink, FileText } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import UiSelect from './UiSelect.vue'
import SkeletonState from './SkeletonState.vue'
import { date } from '../lib/format'
import { notifyError } from '../lib/notifications'
const store = useWorkspace(),
  dialog = ref<HTMLDialogElement | null>(null)
const editing = ref(false),
  draft = ref(''),
  saving = ref(false),
  error = ref('')
const dirty = computed(() => editing.value && draft.value !== store.drawer?.content)
const latest = computed(
  () => store.drawer?.selectedVersion === Math.max(...(store.drawer?.versions ?? [])),
)
const editor = ref<HTMLTextAreaElement | null>(null)
async function beginEdit() {
  if (!store.drawer?.memoId || !latest.value) return
  draft.value = store.drawer.content
  error.value = ''
  editing.value = true
  await nextTick()
  editor.value?.focus()
}
function cancelEdit() {
  editing.value = false
  error.value = ''
}
async function save() {
  const doc = store.drawer
  if (saving.value || !doc?.memoId || !doc.selectedVersion || !dirty.value) return
  saving.value = true
  error.value = ''
  try {
    await store.editMemo(doc.memoId, draft.value, doc.selectedVersion)
    editing.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '메모 저장에 실패했습니다.'
    notifyError(e)
  } finally {
    saving.value = false
  }
}
let priorFocus: HTMLElement | null = null
watch(
  () => store.drawer,
  async (doc) => {
    editing.value = false
    draft.value = ''
    error.value = ''
    await nextTick()
    if (doc && dialog.value) {
      if (!dialog.value.open) {
        priorFocus = document.activeElement as HTMLElement
        dialog.value.showModal()
      }
      if (doc.readRef) await store.markRead(doc.readRef)
      await nextTick()
      if (doc.paragraph != null)
        dialog.value
          .querySelector(`#source-paragraph-${doc.paragraph}`)
          ?.scrollIntoView({ block: 'center', behavior: 'instant' })
    } else if (dialog.value?.open) {
      dialog.value.close()
      priorFocus?.focus()
    }
  },
  { flush: 'post' },
)
function changeVersion(value: string | number | undefined) {
  if (saving.value || editing.value) return
  const v = Number(value),
    doc = store.drawer
  if (doc?.memoId) store.openMemo(doc.memoId, v)
  else if (doc?.filingId) store.openFiling(doc.filingId, v)
}
function close() {
  if (
    saving.value ||
    (dirty.value && !window.confirm('저장하지 않은 수정 내용을 버리고 닫을까요?'))
  )
    return
  store.drawer = null
}
onBeforeUnmount(() => dialog.value?.close())
</script>
<template>
  <dialog
    ref="dialog"
    class="document-drawer"
    :class="{ 'memo-reader': !!store.drawer?.memoId }"
    aria-labelledby="source-title"
    @cancel.prevent="close"
    @click="$event.target === dialog && close()"
  >
    <template v-if="store.drawer">
      <div class="drawer-header">
        <div class="eyebrow">
          <FileText :size="14" /> {{ store.drawer?.memoId ? '메모' : '원문,근거 확인' }}
        </div>
        <div class="memo-actions">
          <button
            v-if="store.drawer.memoId && !store.drawerLoading && !editing"
            class="button secondary"
            type="button"
            :disabled="!latest"
            :title="latest ? '메모 수정' : '최신 버전을 선택한 뒤 수정할 수 있습니다.'"
            @click="beginEdit"
          >
            수정
          </button>
          <button class="icon-button" aria-label="원문 닫기" :disabled="saving" @click="close">
            <X :size="20" />
          </button>
        </div>
      </div>
      <div v-if="store.drawerLoading" class="drawer-body">
        <h2 id="source-title" class="sr-only">메모</h2>
        <SkeletonState variant="document" :rows="5" />
      </div>
      <div v-else class="drawer-body">
        <p class="muted small">{{ store.drawer.subtitle }}</p>
        <h2 id="source-title">{{ store.drawer.title }}</h2>
        <div class="document-meta">
          <span>{{ date(store.drawer.publishedAt, true) }}</span
          ><span v-if="store.drawer.location">{{ store.drawer.location }}</span>
          <div v-if="store.drawer.versions" class="version-label">
            문서 버전
            <UiSelect
              :model-value="store.drawer.selectedVersion"
              :disabled="editing || saving"
              aria-label="문서 버전"
              :options="store.drawer.versions.map((v) => ({ value: v, label: `v${v}` }))"
              @update:model-value="changeVersion"
            />
          </div>
        </div>
        <form v-if="editing" class="memo-edit-form" aria-label="메모 수정" @submit.prevent="save">
          <label for="memo-editor">메모 본문</label>
          <textarea id="memo-editor" ref="editor" v-model="draft" required :disabled="saving" />
          <p class="small muted">저장하면 새 버전이 추가되고 기존 버전은 보존됩니다.</p>
          <p v-if="error" class="field-error" role="alert">{{ error }}</p>
          <div class="memo-actions">
            <button class="button secondary" type="button" :disabled="saving" @click="cancelEdit">
              수정 취소
            </button>
            <button
              class="button primary"
              type="submit"
              :disabled="saving || !dirty || !draft.trim()"
            >
              {{ saving ? '저장 중…' : '저장' }}
            </button>
          </div>
        </form>
        <div v-else class="source-content">
          <p
            v-for="(p, i) in store.drawer.content.split(/\n\s*\n/)"
            :id="`source-paragraph-${i}`"
            :key="i"
            :class="{ highlighted: store.drawer.paragraph === i }"
          >
            {{ p }}
          </p>
        </div>
        <a
          v-if="store.drawer.url"
          class="button secondary full-width"
          :href="store.drawer.url"
          target="_blank"
          rel="noopener noreferrer"
          >외부 원문 열기 <ExternalLink :size="15"
        /></a>
      </div>
    </template>
  </dialog>
</template>

<style scoped>
.memo-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
.memo-edit-form {
  display: grid;
  gap: 16px;
}
.memo-edit-form textarea {
  width: 100%;
  min-height: 320px;
  max-height: 60dvh;
  resize: vertical;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  color: var(--ink);
  background: var(--surface);
  line-height: 1.8;
}
.memo-edit-form textarea:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
</style>
