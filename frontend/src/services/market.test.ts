import { expect, it, vi } from 'vitest'
import { getWatchlistQuotes } from './market'
import { request } from './http'
vi.mock('./http', () => ({ request: vi.fn() }))

it('maps stock codes to company ids and excludes unsupported codes', async () => {
  vi.mocked(request).mockResolvedValue({
    items: {
      '005930': { price: 90000, changePercent: -1, tradingValue: 123, marketCap: 456 },
    },
  })
  const result = await getWatchlistQuotes([
    { id: 'company1', code: '005930' },
    { id: 'company2', code: '005930' },
    { id: 'us', code: 'AAPL' },
    { id: 'missing', code: '900010' },
  ])
  expect(request).toHaveBeenCalledWith('/market/stocks?codes=005930,900010', {}, false)
  expect(Object.keys(result)).toEqual(['company1', 'company2'])
  expect(result.company1?.changePercent).toBe(-1)
})
