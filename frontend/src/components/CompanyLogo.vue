<script setup lang="ts">
import { computed, ref, watch } from 'vue'
const props = defineProps<{ code: string; name: string }>()
const failed = ref(false),
  loaded = ref(false)
const url = computed(() =>
  /^[0-9]{6}$/.test(props.code)
    ? `https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock${props.code}.png`
    : '',
)
watch(
  () => props.code,
  () => {
    failed.value = false
    loaded.value = false
  },
)
</script>
<template>
  <span class="company-logo" :class="{ 'has-image': loaded && !failed }" aria-hidden="true">
    <span v-if="!loaded || failed">{{ name.normalize('NFC').slice(0, 1) }}</span>
    <img
      v-if="url && !failed"
      :key="url"
      :src="url"
      alt=""
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      @load="loaded = true"
      @error="failed = true"
    />
  </span>
</template>
<style scoped>
.company-logo {
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
}
.company-logo.has-image {
  background: #fff;
}
img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  padding: 4px;
}
</style>
