<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseDate, type DateValue } from '@internationalized/date'
import { CalendarIcon } from 'lucide-vue-next'
import { Calendar } from './ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Button } from './ui/button'
const props = defineProps<{ min?: string; max?: string; label: string }>()
const model = defineModel<string>({ required: true })
const open = ref(false)
const selected = computed(() => parseDate(model.value))
function choose(value: DateValue | undefined) {
  if (!value) return
  model.value = value.toString()
  open.value = false
}
</script>
<template>
  <div class="ui-date">
    <Popover v-model:open="open">
      <PopoverTrigger as-child>
        <Button variant="outline" class="w-full justify-between" :aria-label="label">
          {{ model.replaceAll('-', '. ') + '.' }}<CalendarIcon data-icon="inline-end" />
        </Button>
      </PopoverTrigger>
      <PopoverContent class="w-auto p-0" align="end" :collision-padding="16">
        <Calendar
          :model-value="selected"
          :default-placeholder="selected"
          :min-value="min ? parseDate(min) : undefined"
          :max-value="max ? parseDate(max) : undefined"
          locale="ko-KR"
          prevent-deselect
          initial-focus
          @update:model-value="choose"
        />
      </PopoverContent>
    </Popover>
  </div>
</template>
