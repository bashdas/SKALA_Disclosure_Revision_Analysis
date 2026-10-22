<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, useId, watch } from 'vue'
import { PopoverRoot, PopoverAnchor, PopoverPortal, PopoverContent } from 'reka-ui'
import { renderMarkdown, type MarkdownRange } from '../lib/markdown'
import { date } from '../lib/format'
import type { Evidence } from '../types/domain'
const props = withDefaults(
  defineProps<{ content: string; evidence?: Evidence[]; range?: MarkdownRange }>(),
  {
    evidence: () => [],
  },
)
const emit = defineEmits<{ openEvidence: [evidence: Evidence] }>()
const html = computed(() =>
  renderMarkdown(
    props.content,
    props.evidence.map((e) => e.id),
    props.range,
  ),
)
const article = ref<HTMLElement | null>(null)
const anchor = shallowRef<HTMLElement | null>(null)
const preview = shallowRef<Evidence | null>(null)
const previewId = useId()
let closeTimer: ReturnType<typeof setTimeout> | undefined

function cancelClose() {
  clearTimeout(closeTimer)
}
function closePreview() {
  cancelClose()
  anchor.value?.removeAttribute('aria-describedby')
  preview.value = null
  anchor.value = null
}
function scheduleClose() {
  cancelClose()
  closeTimer = setTimeout(closePreview, 150)
}
function reference(event: Event) {
  const target =
    event.target instanceof Element
      ? event.target.closest<HTMLElement>('button[data-evidence-id]')
      : null
  if (!target || !article.value?.contains(target)) return null
  const source = props.evidence.find((e) => e.id === target.dataset.evidenceId)
  return source ? { target, source } : null
}
function showPreview(event: Event) {
  if ('pointerType' in event && event.pointerType === 'touch') return
  const match = reference(event)
  if (!match) return
  closePreview()
  anchor.value = match.target
  preview.value = match.source
  match.target.setAttribute('aria-describedby', previewId)
}
function leaveReference(event: MouseEvent | FocusEvent) {
  const match = reference(event)
  if (match && event.relatedTarget instanceof Node && match.target.contains(event.relatedTarget))
    return
  if (match) scheduleClose()
}
function openReference(event: Event) {
  const match = reference(event)
  if (!match) return
  closePreview()
  emit('openEvidence', match.source)
}
watch(() => [props.content, props.evidence, props.range], closePreview)
onBeforeUnmount(closePreview)
</script>
<template>
  <article
    ref="article"
    class="markdown-body"
    @pointerover="showPreview"
    @pointerout="leaveReference"
    @focusin="showPreview"
    @focusout="leaveReference"
    @keydown.esc="closePreview"
    @click="openReference"
    v-html="html"
  ></article>
  <PopoverRoot :open="!!preview" @update:open="!$event && closePreview()">
    <PopoverAnchor :reference="anchor ?? undefined" />
    <PopoverPortal>
      <PopoverContent
        v-if="preview"
        as-child
        side="top"
        align="start"
        :side-offset="8"
        :collision-padding="16"
        hide-when-detached
        @open-auto-focus.prevent
        @close-auto-focus.prevent
        @pointerenter="cancelClose"
        @pointerleave="scheduleClose"
      >
        <div :id="previewId" class="evidence-preview" role="tooltip">
          <strong>{{ anchor?.textContent }} · {{ preview.title }}</strong>
          <p v-if="preview.location || preview.publishedAt" class="evidence-meta">
            {{ preview.location
            }}<template v-if="preview.publishedAt"> · {{ date(preview.publishedAt) }}</template>
          </p>
          <blockquote>{{ preview.quote || preview.context }}</blockquote>
          <p class="evidence-hint">
            근거 번호를 누르면 {{ preview.url ? '상세 내용과 원문 링크를' : '상세 내용을' }} 확인할
            수 있습니다.
          </p>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
<style scoped>
.markdown-body :deep(.evidence-reference) {
  display: inline;
  padding: 1px 5px;
  border: 0;
  border-radius: 4px;
  color: var(--primary);
  background: var(--primary-soft);
  font: inherit;
  font-weight: 600;
  line-height: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.markdown-body :deep(.evidence-reference:hover) {
  background: var(--surface-strong);
}
.markdown-body :deep(.evidence-reference:focus-visible) {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
.evidence-preview {
  z-index: 60;
  width: 360px;
  max-width: calc(100vw - 32px);
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--card);
  color: var(--ink);
  box-shadow: 0 8px 28px #0002;
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.evidence-preview strong {
  display: block;
}
.evidence-meta,
.evidence-hint {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.evidence-preview blockquote {
  margin: 12px 0 0;
  padding-left: 12px;
  border-left: 2px solid var(--line);
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 6;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.markdown-body {
  padding: 28px;
  color: var(--ink);
  font: inherit;
  line-height: 1.85;
  overflow-wrap: anywhere;
  min-width: 0;
}
.markdown-body :deep(h1) {
  font-size: 26px;
  line-height: 1.5;
  margin: 0 0 24px;
}
.markdown-body :deep(h2) {
  font-size: 21px;
  margin: 32px 0 14px;
}
.markdown-body :deep(h3) {
  font-size: 17px;
  margin: 24px 0 12px;
}
.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 16px;
}
.markdown-body :deep(li) {
  margin-bottom: 7px;
}
.markdown-body :deep(.markdown-table) {
  overflow-x: auto;
  margin: 20px 0 28px;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  table-layout: fixed;
  font-size: 14px;
  line-height: 1.75;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--line);
  padding: 12px 14px;
  text-align: left;
  vertical-align: top;
}
.markdown-body :deep(th) {
  background: var(--surface-strong);
  font-weight: 650;
}
.markdown-body :deep(blockquote) {
  margin: 16px 0;
  padding: 16px 20px;
  background: var(--surface);
  border-radius: 8px;
}
.markdown-body :deep(blockquote p:last-child) {
  margin-bottom: 0;
}
.markdown-body :deep(a) {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 3px;
}
.markdown-body :deep(pre) {
  white-space: pre-wrap;
  background: var(--surface);
  padding: 16px;
  border-radius: 8px;
}
@media (max-width: 650px) {
  .markdown-body {
    padding: 20px;
  }
  .markdown-body :deep(table) {
    min-width: 560px;
  }
}
</style>
