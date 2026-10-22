import { expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CompanyAnalysisHistory from './CompanyAnalysisHistory.vue'
import { useWorkspace } from '../stores/workspace'
import type { AnalysisTask, Filing, ReviewReport } from '../types/domain'

vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/http', async () => ({ currentUser: (await import('vue')).ref(null) }))

it('shows each analysis once with its report or progress, including deleted-memo results and status filters', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkspace()
  store.tasks = [
    {
      id: 'done',
      companyId: 'company',
      filingId: 'filing',
      memoId: 'deleted',
      baseMemoVersion: 2,
      status: 'COMPLETED',
      createdAt: '2026-10-22T10:00:00Z',
    },
    {
      id: 'running',
      companyId: 'company',
      filingId: 'filing',
      memoId: 'memo',
      baseMemoVersion: 1,
      status: 'RUNNING',
      createdAt: '2026-10-22T11:00:00Z',
    },
    {
      id: 'failed',
      companyId: 'company',
      filingId: 'filing',
      memoId: 'memo',
      baseMemoVersion: 1,
      status: 'FAILED',
      createdAt: '2026-10-22T09:00:00Z',
    },
    { id: 'other', companyId: 'other', status: 'COMPLETED', createdAt: '2026-10-22T12:00:00Z' },
  ] as AnalysisTask[]
  store.filings = [{ id: 'filing', title: '공급계약 변경 공시' }] as Filing[]
  store.reports = [
    { id: 'report', taskId: 'done', title: '저장된 AI 보고서', savedAt: '2026-10-22T10:01:00Z' },
  ] as ReviewReport[]
  const wrapper = mount(CompanyAnalysisHistory, {
    props: { companyId: 'company' },
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: RouterLinkStub,
        UiSelect: {
          props: ['modelValue', 'options'],
          emits: ['update:modelValue'],
          template:
            '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="o in options" :value="o.value">{{o.label}}</option></select>',
        },
      },
    },
  })
  const rows = () => wrapper.findAll('.analysis-row')
  expect(wrapper.get('h2').text()).toContain('AI 보고서 3')
  expect(rows()).toHaveLength(3)
  expect(rows()[0]!.text()).toContain('분석 중')
  expect(rows()[0]!.findComponent(RouterLinkStub).props('to')).toBe('/analyses/running')
  expect(
    wrapper.findAll('.text-button').filter((link) => link.text().includes('보고서 보기')),
  ).toHaveLength(1)
  expect(rows()[1]!.text()).toContain('저장된 AI 보고서')
  expect(rows()[1]!.text()).toContain('기준 메모 확인 불가 · 기준 v2')
  expect(rows()[1]!.get('.text-button').text()).toContain('보고서 보기')
  expect(rows()[2]!.get('.text-button').text()).toContain('분석 확인')
  await wrapper.get('select').setValue('COMPLETED')
  expect(rows()).toHaveLength(1)
  expect(rows()[0]!.text()).toContain('저장된 AI 보고서')
  await wrapper.get('select').setValue('FAILED')
  expect(rows()).toHaveLength(1)
  expect(rows()[0]!.text()).toContain('실패')
  await wrapper.get('select').setValue('CANCELLED')
  expect(rows()).toHaveLength(0)
  expect(wrapper.text()).toContain('해당 상태의 분석이 없습니다')
  await wrapper.get('select').setValue('')
  expect(rows()).toHaveLength(3)
  expect(store.tasks).toHaveLength(4)
  expect(store.reports).toHaveLength(1)
  wrapper.unmount()
})
