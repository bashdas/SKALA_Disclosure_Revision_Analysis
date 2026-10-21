<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X, ExternalLink, FileText } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import UiSelect from './UiSelect.vue'
import SkeletonState from './SkeletonState.vue'
import { date } from '../lib/format'
const store = useWorkspace(),
  dialog = ref<HTMLDialogElement | null>(null)
let priorFocus: HTMLElement | null = null
watch(
  () => store.drawer,
  async (doc) => {
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
  const v = Number(value),
    doc = store.drawer
  if (doc?.memoId) store.openMemo(doc.memoId, v)
  else if (doc?.filingId) store.openFiling(doc.filingId, v)
}
function close() {
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
        <div class="eyebrow"><FileText :size="14" /> {{ store.drawer?.memoId ? '메모' : '원문,근거 확인' }}</div>
        <button class="icon-button" aria-label="원문 닫기" @click="close"><X :size="20" /></button>
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
              aria-label="문서 버전"
              :options="store.drawer.versions.map((v) => ({ value: v, label: `v${v}` }))"
              @update:model-value="changeVersion"
            />
          </div>
        </div>
        <div class="source-content">
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
