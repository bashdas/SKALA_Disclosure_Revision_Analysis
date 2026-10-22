<script setup lang="ts">
import { onMounted, onBeforeUnmount, shallowRef, nextTick } from 'vue'
import { Toaster } from './ui/sonner'
import { showQueuedNotice } from '../lib/notifications'
import { useTheme } from '../stores/theme'
import 'vue-sonner/style.css'
const theme = useTheme()
const target = shallowRef<HTMLElement | null>(null)
let observer: MutationObserver | undefined
onMounted(async () => {
  const update = () => {
    target.value =
      [...document.querySelectorAll<HTMLDialogElement>('dialog[open]')].at(-1) ?? document.body
  }
  update()
  await nextTick()
  showQueuedNotice()
  observer = new MutationObserver(update)
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['open'],
  })
})
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <Teleport v-if="target" :to="target"
    ><Toaster
      position="top-center"
      :theme="theme.theme"
      :offset="24"
      :mobile-offset="16"
      :duration="4500"
      close-button
  /></Teleport>
</template>
