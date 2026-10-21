import { request } from './http'

export interface MarketQuote {
  name: string
  value: number | null
  previous_close: number | null
  change_percent: number | null
  change_bp: number | null
  as_of: string | null
  series: number[]
  status: 'available' | 'unavailable'
}
export interface MarketSnapshot {
  source: string
  fetched_at: string
  items: MarketQuote[]
}
export function getMarketIndices() {
  return request<MarketSnapshot>('/market/indices', {}, false)
}

export interface WatchlistQuote {
  price: number
  changePercent: number | null
  tradingValue: number | null
  marketCap: number | null
}
export async function getWatchlistQuotes(
  companies: { id: string; code: string }[],
): Promise<Record<string, WatchlistQuote>> {
  const codes = [...new Set(companies.map((c) => c.code).filter((c) => /^[0-9]{6}$/.test(c)))]
  const items: Record<string, WatchlistQuote> = {}
  for (let offset = 0; offset < codes.length; offset += 50) {
    const result = await request<{ items: Record<string, WatchlistQuote> }>(
      '/market/stocks?codes=' + codes.slice(offset, offset + 50).join(','),
      {},
      false,
    )
    Object.assign(items, result.items)
  }
  return Object.fromEntries(
    companies.filter((c) => items[c.code]).map((c) => [c.id, items[c.code]!]),
  )
}
