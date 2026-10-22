<script lang="ts" setup>
import type { ToasterProps } from 'vue-sonner'
import {
  CircleCheck as CheckCircledIcon,
  Info as InfoCircledIcon,
  LoaderCircle as ReloadIcon,
  CircleAlert as CrossCircledIcon,
  TriangleAlert as ExclamationTriangleIcon,
  X as Cross2Icon,
} from 'lucide-vue-next'
import { cn } from '@/lib/utils'
import { Toaster as Sonner } from 'vue-sonner'

const props = defineProps<ToasterProps>()
</script>

<template>
  <Sonner
    :class="cn('toaster group', props.class)"
    :style="{
      '--normal-bg': 'var(--card)',
      '--normal-text': 'var(--ink)',
      '--normal-border': 'var(--line)',
      '--border-radius': '10px',
    }"
    v-bind="props"
  >
    <template #success-icon>
      <CheckCircledIcon class="size-4" />
    </template>
    <template #info-icon>
      <InfoCircledIcon class="size-4" />
    </template>
    <template #warning-icon>
      <ExclamationTriangleIcon class="size-4" />
    </template>
    <template #error-icon>
      <CrossCircledIcon class="size-4" />
    </template>
    <template #loading-icon>
      <div>
        <ReloadIcon class="size-4 animate-spin" />
      </div>
    </template>
    <template #close-icon>
      <Cross2Icon class="size-4" />
    </template>
  </Sonner>
</template>
