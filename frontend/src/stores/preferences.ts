import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

// Demo identities only. Authentication and authorization remain server concerns.
export const demoUsers = [
  {
    id: 'battery-ra',
    name: '이지원',
    role: 'Research Analyst',
    field: '이차전지 소재',
    companyIds: ['lnf'],
  },
  {
    id: 'shipbuilding-ra',
    name: '김도윤',
    role: 'Research Analyst',
    field: '조선·해양',
    companyIds: ['shi'],
  },
] as const
const STORAGE_KEY = 'disclosure-check.preferences.v1'
interface Preferences {
  activeUserId: string
  favorites: Record<string, string[]>
}
function load(): Preferences {
  const defaults: Preferences = {
    activeUserId: demoUsers[0].id,
    favorites: Object.fromEntries(demoUsers.map((u) => [u.id, [...u.companyIds]])),
  }
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
    if (!value || typeof value !== 'object') return defaults
    if (demoUsers.some((u) => u.id === value.activeUserId))
      defaults.activeUserId = value.activeUserId
    for (const user of demoUsers) {
      const ids = value.favorites?.[user.id]
      if (Array.isArray(ids))
        defaults.favorites[user.id] = [
          ...new Set(ids.filter((id): id is string => typeof id === 'string')),
        ]
    }
  } catch {
    /* Browser preferences are optional; never prevent opening the UI. */
  }
  return defaults
}
export const usePreferences = defineStore('preferences', () => {
  const saved = load()
  const activeUserId = ref(saved.activeUserId),
    favorites = ref(saved.favorites)
  const user = computed(() => demoUsers.find((u) => u.id === activeUserId.value) ?? demoUsers[0])
  const favoriteIds = computed(() => favorites.value[user.value.id] ?? [])
  const storageNotice = ref('')
  function persist() {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ activeUserId: activeUserId.value, favorites: favorites.value }),
      )
      storageNotice.value = ''
    } catch {
      storageNotice.value = '브라우저 저장을 사용할 수 없어 관심종목은 현재 화면에서만 유지됩니다.'
    }
  }
  function selectUser(id: string) {
    if (!demoUsers.some((u) => u.id === id)) return
    activeUserId.value = id
    persist()
  }
  function isFavorite(id: string) {
    return favoriteIds.value.includes(id)
  }
  function toggleFavorite(id: string) {
    const ids = favoriteIds.value
    favorites.value[user.value.id] = ids.includes(id)
      ? ids.filter((item) => item !== id)
      : [...ids, id]
    persist()
  }
  return { user, activeUserId, favoriteIds, storageNotice, selectUser, isFavorite, toggleFavorite }
})
