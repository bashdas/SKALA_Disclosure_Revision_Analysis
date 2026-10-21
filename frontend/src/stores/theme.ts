import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useTheme = defineStore('theme', () => {
  const theme = ref<'light' | 'dark'>(
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
  )

  function toggle() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
    document.documentElement.dataset.theme = theme.value
    try {
      localStorage.setItem('disclosure-check.theme.v1', theme.value)
    } catch {
      // Keep switching usable even when the browser cannot persist the choice.
    }
  }

  return { theme, toggle }
})
