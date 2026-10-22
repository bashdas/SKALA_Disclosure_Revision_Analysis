import { expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AnalysisView from './AnalysisView.vue'
import { useWorkspace } from '../stores/workspace'
import type { AnalysisTask, ReviewReport } from '../types/domain'
vi.mock('../services', () => ({ services: {} }))
it('opens all five report sections initially and allows each to collapse and reopen', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkspace()
  store.tasks = [{ id: 'task', status: 'COMPLETED', currentStage: 'REPORT_SAVE', perspectives: [], asOf: '2026-10-21T00:00:00Z' }] as unknown as AnalysisTask[]
  store.reports = [{ id: 'report', taskId: 'task', title: '검토 결과', summary: '요약', content: '# 본문', changes: [], findings: [], evidence: [], warnings: [] }] as unknown as ReviewReport[]
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/analyses/:taskId', component: AnalysisView }] })
  await router.push('/analyses/task')
  const wrapper = mount(AnalysisView, { global: { plugins: [pinia, router] } })
  expect(wrapper.text()).not.toContain('RESEARCH IMPACT REVIEW')
  expect(wrapper.find('.warning-section').exists()).toBe(false)
  const toggles = wrapper.findAll('[data-slot=collapsible-trigger]')
  expect(toggles.map(t => t.text())).toEqual(['검토 보고서', '보고서 본문', '기존 논리의 재검토0', '근거 자료0', '선택한 분석 관점'])
  for (const toggle of toggles) {
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    await flushPromises()
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    await flushPromises()
    expect(toggle.attributes('aria-expanded')).toBe('true')
  }
  wrapper.unmount()
})
