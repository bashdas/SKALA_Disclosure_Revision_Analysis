<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { request } from '../services/http'
import type { Company } from '../types/domain'
import { useWorkspace } from '../stores/workspace'
import EmptyState from '../components/EmptyState.vue'
import CompanyQuotesTable from '../components/CompanyQuotesTable.vue'
const store = useWorkspace(),
  query = ref(''),
  companies = ref<Company[]>([]),
  total = ref(0),
  hasMore = ref(true),
  loading = ref(false),
  error = ref(''),
  sentinel = ref<HTMLElement | null>(null)
let offset = 0,
  generation = 0,
  observer: IntersectionObserver | undefined,
  debounce: ReturnType<typeof setTimeout>
async function load(reset = false) {
  if (!reset && (loading.value || !hasMore.value)) return
  if (reset) {
    generation++
    offset = 0
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
    }>(`/disclosures/companies?query=${encodeURIComponent(query.value.trim())}&offset=${offset}`)
    if (current !== generation) return
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
  <div class="section-heading">
    <h1 class="company-list-title">
      리서치 기업 <span class="count">{{ total }}</span>
    </h1>
    <form @submit.prevent="load(true)">
      <label class="sr-only" for="company-search">기업 검색</label
      ><input
        id="company-search"
        v-model="query"
        class="compact-search"
        type="search"
        placeholder="기업명 또는 종목코드 검색"
        maxlength="100"
      />
    </form>
  </div>
  <section v-if="companies.length" class="surface company-directory" aria-label="리서치 기업 목록">
    <CompanyQuotesTable :companies="companies" directory />
  </section>
  <EmptyState
    v-if="!loading && !companies.length && !error"
    title="등록된 기업이 없습니다"
    message="기업 자료가 준비되면 이곳에서 업데이트를 확인할 수 있습니다."
  />
  <p v-if="error" role="alert" class="inline-warning">
    {{ error }} <button class="text-button" @click="load(true)">다시 시도</button>
  </p>
  <div ref="sentinel" class="loading-state" role="status">
    <span v-if="loading">기업을 불러오는 중입니다.</span
    ><button v-else-if="hasMore" class="text-button" @click="load()">더 보기</button>
  </div>
</template>
