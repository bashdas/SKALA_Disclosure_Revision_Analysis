import { request } from './http'

export interface InternalReport {
  id: string
  title: string
  corp_code: string
  company_name: string
  published_at: string
  current_version: number
  created_at: string
  updated_at: string
}
export interface InternalReportDetail extends InternalReport {
  content: string
  original_filename: string
}
export interface InternalReportVersion {
  version: number
  title: string
  published_at: string
  original_filename: string
  created_at: string
}
export interface ReportMetadata {
  title: string
  corp_code: string
  published_at: string
}
const base = '/internal-reports'
export const listInternalReports = (offset = 0, corpCode = '') =>
  request<InternalReport[]>(
    `${base}?limit=20&offset=${offset}${corpCode ? '&corp_code=' + encodeURIComponent(corpCode) : ''}`,
  )
export const getInternalReport = (id: string) => request<InternalReportDetail>(`${base}/${id}`)
export const getReportVersions = (id: string, offset = 0) =>
  request<InternalReportVersion[]>(`${base}/${id}/versions?limit=20&offset=${offset}`)
export function createInternalReport(metadata: ReportMetadata, file: File) {
  const form = new FormData()
  for (const [key, value] of Object.entries(metadata)) form.append(key, value)
  form.append('file', file)
  return request<InternalReport>(base, { method: 'POST', body: form })
}
export const editInternalReport = (id: string, metadata: ReportMetadata, version: number) =>
  request<InternalReport>(`${base}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...metadata, base_version: version }),
  })
export function replaceReportPdf(id: string, file: File, version: number) {
  const form = new FormData()
  form.append('file', file)
  form.append('base_version', String(version))
  return request<InternalReport>(`${base}/${id}/versions`, { method: 'POST', body: form })
}
export const deleteInternalReport = (id: string) =>
  request<void>(`${base}/${id}`, { method: 'DELETE' })
export async function downloadInternalReport(id: string, version: number, filename: string) {
  const blob = await request<Blob>(`${base}/${id}/file?version=${version}`, {}, true, 'blob')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
