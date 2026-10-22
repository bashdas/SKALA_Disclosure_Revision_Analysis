<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { request } from '../services/http'
import type { Company } from '../types/domain'
import { useWorkspace } from '../stores/workspace'
import SkeletonState from '../components/SkeletonState.vue'
import EmptyState from '../components/EmptyState.vue'
import CompanyQuotesTable from '../components/CompanyQuotesTable.vue'
import UiSelect from '../components/UiSelect.vue'
const store = useWorkspace(),
  query = ref(''),
  sort = ref<string | number>('market_cap_desc'),
  companies = ref<Company[]>([]),
  total = ref(0),
  hasMore = ref(true),
  loading = ref(false),
  error = ref(''),
  sentinel = ref<HTMLElement | null>(null)
const sortOptions = [
  { value: 'market_cap_desc', label: '시가총액 높은 순' },
  { value: 'market_cap_asc', label: '시가총액 낮은 순' },
  { value: 'name', label: '기업명순' },
]
let offset = 0,
  rankingSnapshot = '',
  generation = 0,
  observer: IntersectionObserver | undefined,
  debounce: ReturnType<typeof setTimeout>
async function load(reset = false) {
  if (!reset && (loading.value || !hasMore.value)) return
  if (reset) {
    generation++
    offset = 0
    rankingSnapshot = ''
    companies.value = []
    hasMore.value = true
  }
  const current = generation
  loading.value = true
  error.value = ''
  try {
    const data = await request<{
      items: { corp_code: string; company_name: string; stock_code: string }[]
      total_count: number
      has_more: boolean
      snapshot?: string
    }>(
      '/disclosures/companies?' +
        new URLSearchParams({
          query: query.value.trim(),
          offset: String(offset),
          sort: String(sort.value),
          ...(rankingSnapshot ? { snapshot: rankingSnapshot } : {}),
        }),
    )
    if (current !== generation) return
    rankingSnapshot = data.snapshot ?? ''
    const batch = data.items.map((c) => ({
      id: c.corp_code,
      name: c.company_name,
      code: c.stock_code,
      sector: '',
      initials: c.company_name.slice(0, 1),
      description: '',
    }))
    companies.value.push(...batch)
    total.value = data.total_count
    hasMore.value = data.has_more
    offset += batch.length
    const known = new Set(store.companies.map((c) => c.id))
    store.companies.push(...batch.filter((c) => !known.has(c.id)))
  } catch (e) {
    if (current === generation) error.value = e instanceof Error ? e.message : '기업 목록 조회 실패'
  } finally {
    if (current === generation) {
      loading.value = false
      await nextTick()
      if (
        !error.value &&
        hasMore.value &&
        sentinel.value &&
        sentinel.value.getBoundingClientRect().top < innerHeight + 200
      )
        void load()
    }
  }
}
watch(query, () => {
  clearTimeout(debounce)
  debounce = setTimeout(() => void load(true), 350)
})
watch(sort, () => {
  clearTimeout(debounce)
  void load(true)
})
onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) void load()
    },
    { rootMargin: '200px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
  void load(true)
})
onBeforeUnmount(() => {
  generation++
  observer?.disconnect()
  clearTimeout(debounce)
})
</script>
<template>
  <div class="section-heading company-directory-heading">
    <h1 class="company-list-title">
      기업 <span class="count">{{ total.toLocaleString('ko-KR') }}</span>
    </h1>
    <form class="company-directory-controls" @submit.prevent="load(true)">
      <label class="sr-only" for="company-search">기업 검색</label
      ><input
        id="company-search"
        v-model="query"
        class="compact-search"
        type="search"
        placeholder="기업명 또는 종목코드 검색"
        maxlength="100"
      />
      <UiSelect v-model="sort" class="company-sort" aria-label="기업 정렬" :options="sortOptions" />
    </form>
  </div>
  <SkeletonState v-if="loading && !companies.length" variant="directory" :rows="8" />
  <section v-if="companies.length" class="surface company-directory" aria-label="기업 목록">
    <CompanyQuotesTable :companies="companies" directory />
  </section>
  <EmptyState
    v-if="!loading && !companies.length && !error"
    title="조회된 기업이 없습니다"
    message="기업 자료가 준비되면 이곳에서 업데이트를 확인할 수 있습니다."
  />
  <p v-if="error" role="alert" class="inline-warning">
    {{ error }} <button class="text-button" @click="load(true)">다시 시도</button>
  </p>
  <div ref="sentinel" class="loading-state" role="status">
    <SkeletonState v-if="loading && companies.length" variant="directory" :rows="2" />
    <button v-if="!loading && hasMore" class="text-button" @click="load()">더 보기</button>
  </div>
</template>

<style scoped>
.company-directory-heading {
  align-items: center;
}
.company-directory-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.company-directory-controls :deep(.company-sort) {
  width: 100%;
  min-height: 36px;
  height: 36px;
  padding-inline: 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 10px;
}
.company-directory-controls :deep(.select-field) {
  width: 172px;
  flex: 0 0 172px;
}
.company-directory-controls .compact-search {
  width: 240px;
  flex: 0 0 240px;
  min-height: 36px;
}
@media (max-width: 650px) {
  .company-directory-heading {
    align-items: flex-start;
  }
  .company-directory-controls {
    width: 100%;
    gap: 8px;
  }
  .company-directory-controls .compact-search {
    width: 0;
    flex: 1;
    min-width: 0;
  }
  .company-directory-controls :deep(.select-field) {
    width: 154px;
    flex-basis: 154px;
  }
  .company-directory-controls :deep(.company-sort) {
    padding-inline: 10px;
  }
}
</style>
