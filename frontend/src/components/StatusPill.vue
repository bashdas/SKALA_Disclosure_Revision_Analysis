<script setup lang="ts">
import type { AnalysisStatus } from '../types/domain'
import { statusLabels } from '../types/domain'
defineProps<{ status: AnalysisStatus }>()
</script>
<template>
  <span class="status-pill" :class="status.toLowerCase()"
    ><span class="status-dot" />{{ statusLabels[status] }}</span
  >
</template>
