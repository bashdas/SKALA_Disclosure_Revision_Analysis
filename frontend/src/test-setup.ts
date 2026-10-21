import { vi } from 'vitest'
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return true
    },
  }),
})

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
