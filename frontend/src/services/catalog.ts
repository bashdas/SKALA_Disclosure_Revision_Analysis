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

export interface CompanyUpdate {
  latest: string | null
  filingCount: number | null
  sector: string | null
  filingStatus: 'available' | 'error'
  sectorStatus: 'available' | 'unavailable' | 'error'
}
const updateCache = new Map<string, { expires: number; value: CompanyUpdate }>()
export async function getCompanyUpdates(
  companies: { id: string; code: string }[],
  onUpdate: (id: string, value: CompanyUpdate) => void,
) {
  const end = koreaDate()
  const startDate = new Date(end + 'T00:00:00Z')
  startDate.setUTCDate(startDate.getUTCDate() - 90)
  const start = startDate.toISOString().slice(0, 10)
  const pending = companies.filter((c) => {
    const cached = updateCache.get(c.id + ':' + c.code)
    if (cached && cached.expires > Date.now()) {
      onUpdate(c.id, cached.value)
      return false
    }
    return true
  })
  let offset = 0
  // ponytail: 최대 네 기업을 동시에 조회합니다. 대량 조회가 필요하면 서버 묶음 도구로 옮깁니다.
  await Promise.all(
    Array.from({ length: Math.min(4, pending.length) }, async () => {
      while (offset < pending.length) {
        const company = pending[offset++]!
        const [filings, sector] = await Promise.allSettled([
          searchDisclosures({ company: company.id, start, end, page: 1 }),
          /^[0-9]{6}$/.test(company.code)
            ? request<{
                items: Record<
                  string,
                  { sector: string | null; status: CompanyUpdate['sectorStatus'] }
                >
              }>('/market/sectors?codes=' + company.code, {}, false)
            : Promise.resolve({
                items: {} as Record<
                  string,
                  { sector: string | null; status: CompanyUpdate['sectorStatus'] }
                >,
              }),
        ])
        const data = sector.status === 'fulfilled' ? sector.value.items[company.code] : undefined
        const value: CompanyUpdate = {
          latest:
            filings.status === 'fulfilled' ? (filings.value.items[0]?.filed_at ?? null) : null,
          filingCount: filings.status === 'fulfilled' ? filings.value.total_count : null,
          filingStatus: filings.status === 'fulfilled' ? 'available' : 'error',
          sector: data?.sector ?? null,
          sectorStatus: data?.status ?? (sector.status === 'rejected' ? 'error' : 'unavailable'),
        }
        if (value.filingStatus !== 'error' && value.sectorStatus !== 'error') {
          updateCache.set(company.id + ':' + company.code, { expires: Date.now() + 300_000, value })
          if (updateCache.size > 200) updateCache.delete(updateCache.keys().next().value!)
        }
        onUpdate(company.id, value)
      }
    }),
  )
}
