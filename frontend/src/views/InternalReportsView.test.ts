import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import InternalReportsView from './InternalReportsView.vue'
import UiSelect from '../components/UiSelect.vue'
import UiDatePicker from '../components/UiDatePicker.vue'
import { createInternalReport } from '../services/internal-reports'

vi.mock('../services/http', () => ({
  currentUser: { value: { role: 'ANALYST' } },
  request: vi
    .fn()
    .mockResolvedValue({ items: [{ corp_code: '00126478', company_name: '삼성중공업' }] }),
}))
vi.mock('../lib/notifications', () => ({ notifyError: vi.fn(), toast: { success: vi.fn() } }))
vi.mock('../services/internal-reports', () => ({
  listInternalReports: vi.fn().mockResolvedValue([]),
  createInternalReport: vi.fn().mockResolvedValue({ id: 'report-1' }),
  getInternalReport: vi
    .fn()
    .mockResolvedValue({ id: 'report-1', title: '검증 리포트', current_version: 1 }),
  getReportVersions: vi.fn().mockResolvedValue([]),
  editInternalReport: vi.fn(),
  deleteInternalReport: vi.fn(),
  downloadInternalReport: vi.fn(),
  replaceReportPdf: vi.fn(),
}))
beforeEach(() => vi.clearAllMocks())
async function registration() {
  const wrapper = mount(InternalReportsView)
  await flushPromises()
  await wrapper
    .findAll('button')
    .find((b) => b.text() === '리포트 등록')!
    .trigger('click')
  return wrapper
}
it('keeps incomplete registration from calling the API', async () => {
  const wrapper = await registration()
  await wrapper.get('form').trigger('submit')
  expect(createInternalReport).not.toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toContain('발행일')
  wrapper.unmount()
})
it('submits the selected company, calendar date and PDF', async () => {
  const wrapper = await registration()
  await wrapper.get('input[maxlength="500"]').setValue('검증 리포트')
  wrapper.findComponent(UiSelect).vm.$emit('update:modelValue', '00126478')
  wrapper.findComponent(UiDatePicker).vm.$emit('update:modelValue', '2026-10-14')
  const file = new File(['%PDF'], 'report.pdf', { type: 'application/pdf' })
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file] })
  await input.trigger('change')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(createInternalReport).toHaveBeenCalledWith(
    { title: '검증 리포트', corp_code: '00126478', published_at: '2026-10-14' },
    file,
  )
  wrapper.unmount()
})
