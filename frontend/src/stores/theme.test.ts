import { readFileSync } from 'node:fs'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { useTheme } from './theme'

const bootstrap = readFileSync('public/theme-init.js', 'utf8')
function initialize() {
  // Execute the actual pre-mount browser script, not a second implementation.
  new Function(bootstrap)()
  return useTheme()
}
beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
  })
  delete document.documentElement.dataset.theme
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it.each([null, 'unexpected', 'LIGHT', '{broken'])(
  '미설정·잘못된 값 %s는 라이트로 시작한다',
  (value) => {
    if (value !== null) localStorage.setItem('disclosure-check.theme.v1', value)
    expect(initialize().theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  },
)
it('저장된 다크를 Vue 시작 전에 적용하고 재시작 시 선택을 유지한다', () => {
  localStorage.setItem('disclosure-check.theme.v1', 'dark')
  const store = initialize()
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(store.theme).toBe('dark')
  store.toggle()
  expect(localStorage.getItem('disclosure-check.theme.v1')).toBe('light')
  expect(document.documentElement.dataset.theme).toBe('light')
  setActivePinia(createPinia())
  expect(initialize().theme).toBe('light')
})
it('관심종목과 읽음 저장값을 변경하지 않는다', () => {
  localStorage.setItem('disclosure-check.preferences.v1', 'existing-favorites')
  localStorage.setItem('disclosure-check.reads.v1', 'existing-reads')
  initialize().toggle()
  expect(localStorage.getItem('disclosure-check.preferences.v1')).toBe('existing-favorites')
  expect(localStorage.getItem('disclosure-check.reads.v1')).toBe('existing-reads')
})
it('저장소 읽기·쓰기가 거부돼도 현재 테마를 전환한다', () => {
  vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  const store = initialize()
  expect(store.theme).toBe('light')
  expect(() => store.toggle()).not.toThrow()
  expect(store.theme).toBe('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
})
