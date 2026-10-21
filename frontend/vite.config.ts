import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'], clearMocks: true },
})
