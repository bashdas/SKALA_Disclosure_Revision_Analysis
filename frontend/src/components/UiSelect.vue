<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select'
defineOptions({ inheritAttrs: false })
const props = defineProps<{
  options: { label: string; value: string | number }[]
  placeholder?: string
  disabled?: boolean
}>()
const open = ref(false)
function restoreFocus(event: Event) {
  event.preventDefault()
  const content = event.target as HTMLElement | null
  const dialog = content?.closest('dialog')
  if (dialog && !dialog.open) return
  const triggerId = content?.getAttribute('aria-labelledby')
  if (triggerId) document.getElementById(triggerId)?.focus()
}
function closeMenu(event: KeyboardEvent) {
  event.preventDefault()
  event.stopPropagation()
  open.value = false
}
const model = defineModel<string | number>()
const selected = computed({
  get: () =>
    model.value === ''
      ? props.options.some((option) => option.value === '')
        ? '__all__'
        : undefined
      : model.value,
  set: (value) => {
    model.value = value === '__all__' ? '' : value
  },
})
</script>
<template>
  <div class="select-field">
  <Select v-model="selected" v-model:open="open" :disabled="disabled">
    <SelectTrigger v-bind="$attrs" class="ui-select w-full px-4"
      ><SelectValue :placeholder="placeholder"
    /></SelectTrigger>
    <SelectContent
      position="popper"
      :side-offset="4"
      :body-lock="false"
      @escape-key-down="closeMenu"
      @close-auto-focus="restoreFocus"
    >
      <SelectGroup>
        <SelectItem
          v-for="option in options"
          :key="option.value"
          :value="option.value === '' ? '__all__' : option.value"
          >{{ option.label }}</SelectItem
        >
      </SelectGroup>
      <p v-if="!options.length" class="px-3 py-2 text-sm text-muted-foreground">
        선택할 항목이 없습니다
      </p>
    </SelectContent>
  </Select>
  </div>
</template>
