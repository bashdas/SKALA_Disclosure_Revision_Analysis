<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from './ui/collapsible'
withDefaults(defineProps<{ title: string; count?: number; defaultOpen?: boolean }>(), {
  defaultOpen: true,
})
</script>
<template>
  <Collapsible as="section" :default-open="defaultOpen" class="report-fold">
    <div class="report-fold-heading">
      <h2>
        <CollapsibleTrigger class="report-fold-trigger"
          >{{ title }}<span v-if="count != null" class="count">{{ count }}</span
          ><ChevronDown
        /></CollapsibleTrigger>
      </h2>
      <div v-if="$slots.actions" class="row-actions"><slot name="actions" /></div>
    </div>
    <CollapsibleContent class="report-fold-content"><slot /></CollapsibleContent>
  </Collapsible>
</template>
<style scoped>
.report-fold-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.report-fold-heading h2 {
  min-width: 0;
}
.report-fold-trigger {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font: inherit;
  color: inherit;
  text-align: left;
}
.report-fold-trigger svg {
  width: 16px;
  height: 16px;
  color: var(--muted);
  transition: transform 150ms ease;
}
.report-fold-trigger[data-state='open'] svg {
  transform: rotate(180deg);
}
.report-fold-content {
  padding-top: 20px;
}
.report-body > .report-fold-heading,
.unified-report > .report-fold-heading,
.perspectives-section > .report-fold-heading {
  padding: 20px 24px;
}
.report-body > .report-fold-content,
.unified-report > .report-fold-content {
  padding-top: 0;
}
.perspectives-section > .report-fold-content {
  padding: 0 24px 24px;
}
</style>
