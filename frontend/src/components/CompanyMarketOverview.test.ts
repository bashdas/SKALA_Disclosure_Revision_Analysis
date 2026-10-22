import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CompanyMarketOverview from './CompanyMarketOverview.vue'
import { getWatchlistQuotes } from '../services/market'
import { request } from '../services/http'
import type { Company } from '../types/domain'
vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/market', () => ({ getWatchlistQuotes: vi.fn() }))
vi.mock('../services/http', async () => ({
  request: vi.fn(),
  currentUser: (await import('vue')).ref(null),
}))
afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})
it('shows a skeleton followed by actual quotes and history, retaining data after refresh failure', async () => {
  vi.useFakeTimers()
  vi.mocked(getWatchlistQuotes)
    .mockResolvedValueOnce({
      company: {
        price: 110,
        openPrice: 101,
        highPrice: 115,
        lowPrice: 98,
        volume: 12345,
        changePercent: 10,
        tradingValue: 2e8,
        marketCap: 3e12,
      },
    })
    .mockRejectedValue(new Error('offline'))
  vi.mocked(request).mockImplementation(async (url) =>
    url.includes('/history/')
      ? {
          series: [100, 105, 110],
          previous_close: 105,
          start_date: '20261001',
          end_date: '20261021',
        }
      : { items: { '005930': { sector: '반도체' } } },
  )
  const wrapper = mount(CompanyMarketOverview, {
    global: { plugins: [createPinia()] },
    props: {
      company: { id: 'company', code: '005930', name: '삼성전자' } as Company,
    },
  })
  expect(wrapper.find('.skeleton-state').exists()).toBe(true)
  await flushPromises()
  expect(wrapper.text()).toContain('12,345주')
  expect(wrapper.text()).toContain('115원')
  expect(wrapper.text()).toContain('110원')
  expect(wrapper.text()).toContain('+10.00%')
  expect(wrapper.text()).toContain('3조원')
  expect(wrapper.text()).toContain('반도체')
  expect(wrapper.find('svg.market-sparkline').exists()).toBe(true)
  await vi.advanceTimersByTimeAsync(60000)
  await flushPromises()
  expect(wrapper.text()).toContain('110원')
  expect(wrapper.text()).toContain('시세 다시 조회')
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(60000)
  expect(getWatchlistQuotes).toHaveBeenCalledTimes(2)
})
