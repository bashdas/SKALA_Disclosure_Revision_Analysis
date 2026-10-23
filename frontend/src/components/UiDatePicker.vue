<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseDate, type DateValue } from '@internationalized/date'
import { CalendarIcon, X } from 'lucide-vue-next'
import { Calendar } from './ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Button } from './ui/button'
const props = defineProps<{ min?: string; max?: string; label: string; placeholder?: string }>()
const model = defineModel<string>({ required: true })
const open = ref(false)
const selected = computed(() => (model.value ? parseDate(model.value) : undefined))
function choose(value: DateValue | undefined) {
  if (!value) return
  model.value = value.toString()
  open.value = false
}
</script>
<template>
  <div class="ui-date" :class="{ 'has-value': model }">
    <Popover v-model:open="open">
      <PopoverTrigger as-child>
        <Button
          variant="outline"
          class="ui-date-trigger w-full justify-between"
          type="button"
          :aria-label="label"
        >
          <span>{{ model ? model.replaceAll('-', '. ') + '.' : placeholder || '전체 기간' }}</span>
          <CalendarIcon v-if="!model" data-icon="inline-end" />
        </Button>
      </PopoverTrigger>
      <PopoverContent class="w-auto p-0" align="end" :collision-padding="16">
        <Calendar
          :model-value="selected"
          :default-placeholder="selected"
          :min-value="min ? parseDate(min) : undefined"
          :max-value="max ? parseDate(max) : undefined"
          locale="ko-KR"
          layout="month-and-year"
          prevent-deselect
          initial-focus
          @update:model-value="choose"
        />
      </PopoverContent>
    </Popover>
    <button
      v-if="model"
      class="ui-date-clear"
      type="button"
      :aria-label="`${label} 초기화`"
      :title="`${label} 초기화`"
      @click="model = ''"
    >
      <X :size="14" aria-hidden="true" />
    </button>
  </div>
</template>
