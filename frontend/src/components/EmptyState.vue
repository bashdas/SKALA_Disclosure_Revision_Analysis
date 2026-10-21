<script setup lang="ts">
import { FolderOpen } from 'lucide-vue-next'
defineProps<{ title: string; message: string }>()
</script>
<template>
  <div class="empty-state">
    <FolderOpen :size="30" :stroke-width="1.4" />
    <h3>{{ title }}</h3>
    <p>{{ message }}</p>
    <slot />
  </div>
</template>
