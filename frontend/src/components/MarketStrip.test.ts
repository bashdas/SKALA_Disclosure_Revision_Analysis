import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MarketStrip from './MarketStrip.vue'
import { getMarketIndices, type MarketSnapshot } from '../services/market'

vi.mock('../services/market', () => ({ getMarketIndices: vi.fn() }))
afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})
const snapshot: MarketSnapshot = {
  source: 'Yahoo Finance',
  fetched_at: '2026-10-21T04:00:00Z',
  items: [
    {
      name: 'KOSPI',
      value: 110,
      previous_close: 100,
      change_percent: 10,
      change_bp: null,
      as_of: '2026-10-21T00:00:00Z',
      series: [100, 105, 110],
      status: 'available',
    },
    {
      name: '미국채 10Y',
      value: 4.25,
      previous_close: 4.2,
      change_percent: 1.19,
      change_bp: 5,
      as_of: '2026-10-20T13:00:00Z',
      series: [4.1, 4.2, 4.25],
      status: 'available',
    },
    {
      name: 'KOSDAQ',
      value: null,
      previous_close: null,
      change_percent: null,
      change_bp: null,
      as_of: null,
      series: [],
      status: 'unavailable',
    },
  ],
}

it('renders actual series, percentage and basis points in the existing cards', async () => {
  vi.mocked(getMarketIndices).mockResolvedValue(snapshot)
  const wrapper = mount(MarketStrip)
  await flushPromises()
  expect(wrapper.findAll('article')).toHaveLength(12)
  expect(wrapper.findAll('svg.market-sparkline')).toHaveLength(2)
  expect(wrapper.text()).toContain('110.00')
  expect(wrapper.text()).toContain('+10.00%')
  expect(wrapper.text()).toContain('4.25%')
  expect(wrapper.text()).toContain('+5.00bp')
  expect(wrapper.text()).toContain('1개 지표 미수신')
  expect(wrapper.text()).not.toContain('KST 수신')
  Object.defineProperty(wrapper.get('.market-rail').element, 'scrollTo', { value: vi.fn() })
  await wrapper.findAll('.market-filters button')[1]!.trigger('click')
  expect(wrapper.findAll('article')).toHaveLength(3)
  wrapper.unmount()
})

it('shows failure and retries without illustrative prices', async () => {
  vi.mocked(getMarketIndices)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue(snapshot)
  const wrapper = mount(MarketStrip)
  await flushPromises()
  expect(wrapper.text()).toContain('시장 지표를 불러오지 못했습니다.')
  expect(wrapper.findAll('svg.market-sparkline')).toHaveLength(0)
  await wrapper.find('.market-status button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('110.00')
  wrapper.unmount()
})

it('marks retained data on refresh failure and stops polling on unmount', async () => {
  vi.useFakeTimers()
  vi.mocked(getMarketIndices)
    .mockResolvedValueOnce(snapshot)
    .mockRejectedValue(new Error('offline'))
  const wrapper = mount(MarketStrip)
  await flushPromises()
  await vi.advanceTimersByTimeAsync(60000)
  await flushPromises()
  expect(wrapper.text()).toContain('이전 수신 값을 표시합니다.')
  expect(wrapper.text()).toContain('110.00')
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(60000)
  expect(getMarketIndices).toHaveBeenCalledTimes(2)
})
