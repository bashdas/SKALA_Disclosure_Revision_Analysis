export interface WatchlistQuote {
  price: number
  changePercent: number
  tradingValue: number
  marketCap: number
}
export async function getWatchlistQuotes(): Promise<Record<string, WatchlistQuote>> {
  // 시세 제공 API가 없어 미수신 값을 빈 목록으로 표시합니다.
  return {}
}
