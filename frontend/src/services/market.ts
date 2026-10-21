// Fixed UI examples only. No real-time or historical market data is queried.
// Monetary values are KRW; changePercent uses percentage points (1.25 = +1.25%).
export interface WatchlistQuote {
  price: number
  changePercent: number
  tradingValue: number
  marketCap: number
}
const exampleQuotes: Record<string, WatchlistQuote> = {
  lnf: { price: 125000, changePercent: 2.15, tradingValue: 18500000000, marketCap: 4500000000000 },
  shi: { price: 24500, changePercent: -0.81, tradingValue: 42700000000, marketCap: 21500000000000 },
  'samsung-electronics': {
    price: 78500,
    changePercent: 1.42,
    tradingValue: 352900000000,
    marketCap: 468600000000000,
  },
  'sk-hynix': {
    price: 210000,
    changePercent: 3.19,
    tradingValue: 422900000000,
    marketCap: 152900000000000,
  },
  'hyundai-motor': {
    price: 245000,
    changePercent: -1.21,
    tradingValue: 86200000000,
    marketCap: 51400000000000,
  },
  kia: { price: 108000, changePercent: 0.75, tradingValue: 48100000000, marketCap: 43200000000000 },
  'lg-energy-solution': {
    price: 385000,
    changePercent: -2.04,
    tradingValue: 65100000000,
    marketCap: 90000000000000,
  },
  'samsung-biologics': {
    price: 1050000,
    changePercent: 0,
    tradingValue: 28100000000,
    marketCap: 74700000000000,
  },
  naver: {
    price: 225000,
    changePercent: 1.58,
    tradingValue: 51800000000,
    marketCap: 36500000000000,
  },
  'kb-financial': {
    price: 98000,
    changePercent: -0.51,
    tradingValue: 32500000000,
    marketCap: 38400000000000,
  },
  'lg-chem': {
    price: 320000,
    changePercent: -1.85,
    tradingValue: 37400000000,
    marketCap: 22600000000000,
  },
  'hanwha-aerospace': {
    price: 650000,
    changePercent: 2.68,
    tradingValue: 128400000000,
    marketCap: 32900000000000,
  },
}

export async function getWatchlistQuotes(): Promise<Record<string, WatchlistQuote>> {
  return structuredClone(exampleQuotes)
}
