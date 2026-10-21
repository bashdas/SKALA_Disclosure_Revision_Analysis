import { expect, it, vi } from 'vitest'
import { request } from './http'
import { getCompanyUpdates } from './catalog'
vi.mock('./http', () => ({ request: vi.fn() }))

it('uses public filing totals and latest dates, caches successful metadata and preserves failures', async () => {
  vi.mocked(request).mockImplementation(async (url) => {
    if (url.startsWith('/market/sectors'))
      return { items: { '005930': { sector: '반도체와반도체장비', status: 'available' } } }
    if (url.includes('corp_code=00126380'))
      return { items: [{ filed_at: '2026-10-20' }], total_count: 125, has_more: true }
    throw new Error('offline')
  })
  const updated = vi.fn()
  await getCompanyUpdates(
    [
      { id: '00126380', code: '005930' },
      { id: 'failed', code: '' },
    ],
    updated,
  )
  expect(updated).toHaveBeenCalledWith(
    '00126380',
    expect.objectContaining({
      latest: '2026-10-20',
      filingCount: 125,
      sector: '반도체와반도체장비',
    }),
  )
  expect(updated).toHaveBeenCalledWith(
    'failed',
    expect.objectContaining({
      latest: null,
      filingCount: null,
      filingStatus: 'error',
    }),
  )
  const calls = vi.mocked(request).mock.calls.length
  await getCompanyUpdates([{ id: '00126380', code: '005930' }], updated)
  expect(request).toHaveBeenCalledTimes(calls)
})
