import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import UiSelect from './UiSelect.vue'
import AnalysisLauncher from './AnalysisLauncher.vue'
import { useWorkspace } from '../stores/workspace'
import { registerDisclosure } from '../services/catalog'
import type { Filing, Memo, AnalysisTask, Company } from '../types/domain'

vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/catalog', () => ({ registerDisclosure: vi.fn() }))

it.each([true, false])('opens and starts with the chosen memo version (correction=%s)', async (isCorrection) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkspace()
  store.companies = [{ id: 'company', name: '기업' }] as Company[]
  store.memos = [
    {
      id: 'memo',
      companyName: '기업',
      title: '기준 메모',
      currentVersion: 2,
      versions: [{ version: 1 }, { version: 2 }],
    },
  ] as Memo[]
  vi.spyOn(store, 'refresh').mockResolvedValue()
  const start = vi.spyOn(store, 'start').mockResolvedValue({ id: 'task' } as AnalysisTask)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/analyses/:taskId', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  const wrapper = mount(AnalysisLauncher, {
    props: { companyId: 'company', filing: null },
    global: { plugins: [pinia, router] },
  })
  const dialog = wrapper.get('dialog').element as HTMLDialogElement
  dialog.showModal = () => dialog.setAttribute('open', '')
  dialog.close = () => dialog.removeAttribute('open')
  await wrapper.setProps({
    filing: {
      id: 'receipt',
      companyId: 'company',
      receiptNo: '20261021000001',
      title: '정정공시',
      isCorrection,
    } as Filing,
  })
  await flushPromises()
  expect(dialog.open).toBe(true)
  expect(registerDisclosure).not.toHaveBeenCalled()
  expect(start).not.toHaveBeenCalled()
  await wrapper.findAllComponents(UiSelect)[0]!.setValue('memo')
  expect(wrapper.findAllComponents(UiSelect)[1]!.props('modelValue')).toBe(2)
  await wrapper.findAllComponents(UiSelect)[1]!.setValue(1)
  vi.mocked(registerDisclosure)
    .mockRejectedValueOnce(new Error('원문 조회 실패'))
    .mockResolvedValueOnce({ id: 'registered' })
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('원문 조회 실패')
  expect(dialog.open).toBe(true)
  expect(start).not.toHaveBeenCalled()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(registerDisclosure).toHaveBeenLastCalledWith('20261021000001')
  expect(start).toHaveBeenCalledWith({ filingId: 'registered', memoId: 'memo', memoVersion: 1 })
  expect(router.currentRoute.value.path).toBe('/analyses/task')
  expect(dialog.open).toBe(false)
  wrapper.unmount()
})
