import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export default defineConfig({
  plugins: [vue()],
  cacheDir: process.env.VITE_CACHE_DIR ?? join(tmpdir(), 'disclosure-check-web', 'vite'),
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'], clearMocks: true },
})
