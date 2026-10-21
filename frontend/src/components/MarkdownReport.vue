<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../lib/markdown'
const props=defineProps<{content:string}>()
const html=computed(()=>renderMarkdown(props.content))
</script>
<template><article class="markdown-body" v-html="html"></article></template>
<style scoped>
.markdown-body { padding:28px; color:var(--ink); font:inherit; line-height:1.85; overflow-wrap:anywhere; min-width:0; }
.markdown-body :deep(h1) { font-size:26px; line-height:1.5; margin:0 0 24px; }
.markdown-body :deep(h2) { font-size:21px; margin:32px 0 14px; }
.markdown-body :deep(h3) { font-size:17px; margin:24px 0 12px; }
.markdown-body :deep(p), .markdown-body :deep(ul), .markdown-body :deep(ol) { margin:0 0 16px; }
.markdown-body :deep(li) { margin-bottom:7px; }
.markdown-body :deep(.markdown-table) { overflow-x:auto; margin:20px 0 28px; }
.markdown-body :deep(table) { border-collapse:collapse; width:100%; table-layout:fixed; font-size:14px; line-height:1.75; }
.markdown-body :deep(th), .markdown-body :deep(td) { border:1px solid var(--line); padding:12px 14px; text-align:left; vertical-align:top; }
.markdown-body :deep(th) { background:var(--surface-strong); font-weight:650; }
.markdown-body :deep(blockquote) { margin:16px 0; padding:16px 20px; background:var(--surface); border-radius:8px; }
.markdown-body :deep(blockquote p:last-child) { margin-bottom:0; }
.markdown-body :deep(a) { color:var(--primary); text-decoration:underline; text-underline-offset:3px; }
.markdown-body :deep(pre) { white-space:pre-wrap; background:var(--surface); padding:16px; border-radius:8px; }
@media(max-width:650px) { .markdown-body { padding:20px; } .markdown-body :deep(table) { min-width:560px; } }
</style>
