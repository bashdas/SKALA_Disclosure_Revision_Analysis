import { defineConfig } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const port = process.env.E2E_PORT ?? '5173'
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './tests',
  outputDir: join(tmpdir(), 'disclosure-check-web', 'playwright'),
  timeout: 25000,
  fullyParallel: true,
  workers: 2,
  expect: { timeout: 10000 },
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: join(tmpdir(), 'disclosure-check-web', 'playwright-report') }],
  ],
  use: {
    baseURL,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1100 } } },
    {
      name: 'mobile',
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI && !process.env.E2E_PORT,
    timeout: 20000,
  },
})
