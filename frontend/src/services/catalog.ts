import { request } from './http'
export interface DisclosureRow {
  receipt_no: string
  corp_code: string
  company_name: string
  report_name: string
  filed_at: string
  is_correction: boolean
  has_corrections: boolean
}
export interface DisclosurePage {
  items: DisclosureRow[]
  total_count: number | null
  has_more: boolean
  next_page?: number
}
export interface FavoriteCompany {
  corp_code: string
  company_name: string
  stock_code: string
}
export const koreaDate = (value = new Date()) =>
  value.toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' })
export function searchDisclosures(
  options: { company?: string; query?: string; start: string; end: string; page: number },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    start_date: options.start,
    end_date: options.end,
    page: String(options.page),
    query: options.query ?? '',
  })
  if (options.company) query.set('corp_code', options.company)
  return request<DisclosurePage>(`/disclosures?${query}`, { signal })
}
export function favoriteCompany(code: string) {
  return request<FavoriteCompany>('/favorites', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ corp_code: code }),
  })
}
export const removeFavorite = (code: string) =>
  request<void>(`/favorites/${code}`, { method: 'DELETE' })
export const registerDisclosure = (receipt: string) =>
  request<{ id: string }>('/filings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ receipt_no: receipt }),
  })
export const unregisterDisclosure = (id: string) =>
  request<void>(`/filings/${id}`, { method: 'DELETE' })
export const checkCorrections = (id: string) =>
  request<unknown[]>(`/filings/${id}/corrections/check`, { method: 'POST' })
