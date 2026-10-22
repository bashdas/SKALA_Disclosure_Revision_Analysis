<script setup lang="ts">
import { toast, notifyError } from '../lib/notifications'
import { computed, ref } from 'vue'
import { Star } from 'lucide-vue-next'
import { useWorkspace } from '../stores/workspace'
import { favoriteCompany, removeFavorite } from '../services/catalog'
const props = defineProps<{ companyId: string; name: string }>()
const store = useWorkspace(),
  busy = ref(false),
  error = ref('')
const selected = computed(() => store.companies.some((c) => c.id === props.companyId && c.favorite))
async function toggle() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const wasSelected = selected.value
    if (wasSelected) await removeFavorite(props.companyId)
    else await favoriteCompany(props.companyId)
    toast.success(wasSelected ? '관심종목에서 해제했습니다.' : '관심종목에 추가했습니다.', {
      description: props.name,
    })
    await store.refresh()
  } catch (e) {
    notifyError(e)
    error.value = e instanceof Error ? e.message : '즐겨찾기를 변경하지 못했습니다.'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <span class="company-favorite-control">
    <button
      class="favorite-button"
      :class="{ selected }"
      :aria-label="`${name} 관심종목 ${selected ? '해제' : '추가'}`"
      :aria-pressed="selected"
      :disabled="busy"
      @click="toggle"
    >
      <Star :size="20" :fill="selected ? 'currentColor' : 'none'" />
    </button>
    <span v-if="error" class="field-error" role="alert">{{ error }}</span>
  </span>
</template>

<style scoped>
.favorite-button.selected :deep(svg) {
  fill: currentColor;
}
</style>
