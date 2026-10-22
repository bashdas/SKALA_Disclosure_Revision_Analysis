import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useWorkspace } from '../stores/workspace'
import CompanyView from './CompanyView.vue'
import { registerDisclosure } from '../services/catalog'
import type { AnalysisTask, Company, Filing, Memo, ReviewReport } from '../types/domain'

vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/catalog', () => ({
  koreaDate: () => '2026-10-21',
  searchDisclosures: vi.fn(async () => ({
    items: [
      {
        receipt_no: 'new',
        corp_code: 'company',
        report_name: '신규 공시',
        filed_at: '2026-10-21',
        is_correction: false,
      },
      {
        receipt_no: 'correction',
        corp_code: 'company',
        report_name: '정정 공시',
        filed_at: '2026-10-21',
        is_correction: true,
      },
    ],
    total_count: 1234,
    has_more: false,
  })),
  registerDisclosure: vi.fn(),
  unregisterDisclosure: vi.fn(),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

it.each(['filings', 'memos', 'reports', 'history'])(
  '%s 목록의 동작을 본문 바깥 오른쪽 영역에 둡니다',
  async (tab) => {
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        observe() {}
        disconnect() {}
      },
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useWorkspace()
    store.companies = [{ id: 'company', name: '기업', code: '123456' }] as Company[]
    store.filings = [
      { id: 'filing', companyId: 'company', title: '분석 대상 공시', isCorrection: true },
    ] as Filing[]
    store.memos = [
      {
        id: 'memo',
        companyName: '기업',
        title: '기업 메모',
        currentVersion: 1,
        createdAt: '2026-10-21',
        updatedAt: '2026-10-21',
        versions: [],
      },
    ] as Memo[]
    store.tasks = [
      {
        id: 'task',
        companyId: 'company',
        filingId: 'filing',
        memoId: 'memo',
        createdAt: '2026-10-21',
        baseMemoVersion: 1,
        status: 'COMPLETED',
      },
    ] as AnalysisTask[]
    store.reports = [
      { id: 'report', taskId: 'task', title: '분석 보고서', savedAt: '2026-10-21', version: 1 },
    ] as ReviewReport[]
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/companies/:companyId', component: CompanyView }],
    })
    await router.push('/companies/company?tab=' + tab)
    const wrapper = mount(CompanyView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.findAll('.tabs a')).toHaveLength(3)
    expect(wrapper.get('.tabs').text()).not.toContain('분석 이력')
    expect(wrapper.find('.company-tools').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('등록')
    const rows = wrapper.findAll('.document-row, .analysis-row')
    expect(rows.length).toBeGreaterThan(0)
    if (tab === 'reports' || tab === 'history') {
      expect(wrapper.get('.tabs a.selected').text()).toContain('AI 보고서')
      expect(rows).toHaveLength(1)
      expect(rows[0]!.text()).toContain('분석 보고서')
      expect(rows[0]!.get('.text-button').text()).toContain('보고서 보기')
    }
    for (const row of rows) {
      expect(row.find('.document-info .document-actions').exists()).toBe(false)
      expect(row.find(':scope > .document-actions').exists()).toBe(true)
    }
    if (tab === 'filings') {
      expect(wrapper.get('.tabs a').text()).toContain('1234')
      expect(rows).toHaveLength(2)
      for (const row of rows) {
        expect(row.get('a.document-title').attributes('target')).toBe('_blank')
        expect(row.find('.document-actions a').exists()).toBe(false)
        expect(row.text()).not.toContain('내용 확인')
      }
      expect(rows[0]!.find('.document-actions').text()).toContain('분석하기')
      expect(rows[1]!.find('.document-actions').text()).toContain('분석하기')
      const dialog = wrapper.get('dialog').element as HTMLDialogElement
      dialog.showModal = () => dialog.setAttribute('open', '')
      dialog.close = () => dialog.removeAttribute('open')
      await rows[0]!.get('.document-actions button').trigger('click')
      await flushPromises()
      expect(dialog.open).toBe(true)
      expect(registerDisclosure).not.toHaveBeenCalled()
    }
    wrapper.unmount()
  },
)
