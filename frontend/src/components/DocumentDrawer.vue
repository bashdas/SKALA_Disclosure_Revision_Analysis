<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X, ExternalLink, FileText } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
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
function changeVersion(event: Event) {
  const v = Number((event.target as HTMLSelectElement).value),
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
    aria-labelledby="source-title"
    @cancel.prevent="close"
    @click="$event.target === dialog && close()"
  >
    <template v-if="store.drawer">
      <div class="drawer-header">
        <div class="eyebrow"><FileText :size="14" /> 원문·근거 확인</div>
        <button class="icon-button" aria-label="원문 닫기" @click="close"><X :size="20" /></button>
      </div>
      <div class="drawer-body">
        <p class="muted small">{{ store.drawer.subtitle }}</p>
        <h2 id="source-title">{{ store.drawer.title }}</h2>
        <div class="document-meta">
          <span>{{ date(store.drawer.publishedAt, true) }}</span
          ><span v-if="store.drawer.location">{{ store.drawer.location }}</span
          ><label v-if="store.drawer.versions" class="version-label"
            >문서 버전
            <select :value="store.drawer.selectedVersion" @change="changeVersion">
              <option v-for="v in store.drawer.versions" :key="v" :value="v">v{{ v }}</option>
            </select></label
          >
        </div>
        <p class="sample-note">
          시연용 문서·요약입니다. 실제 분석이나 원본 보고서로 사용하지 않습니다.
        </p>
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
