import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkspace } from './workspace'
import type { Company, Memo } from '../types/domain'
import { mount } from '@vue/test-utils'
import AnalysisLauncher from '../components/AnalysisLauncher.vue'

vi.mock('../services', () => ({ services: {} }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
beforeEach(() => setActivePinia(createPinia()))

it('uses the same company filter for memo lists and unread counts', () => {
  const store = useWorkspace()
  store.companies = [
    { id: 'a', name: '삼성중공업' },
    { id: 'b', name: '엘앤에프' },
  ] as Company[]
  store.memos = [
    { id: 'a1', companyName: '삼성중공업'.normalize('NFD'), currentVersion: 1 },
    { id: 'b1', companyName: '엘앤에프', currentVersion: 1 },
    { id: 'unknown', companyName: null, currentVersion: 1 },
  ] as Memo[]
  expect(store.memosForCompany('a').map((m) => m.id)).toEqual(['a1'])
  expect(store.memosForCompany('b').map((m) => m.id)).toEqual(['b1'])
  expect(store.memosForCompany('missing')).toEqual([])
  expect(store.countUnread('a', 'memo')).toBe(1)
  store.readKeys.push('memo:a1:v1')
  expect(store.countUnread('a', 'memo')).toBe(0)
})

it('changes the analysis memo options when the selected company changes', async () => {
  const store = useWorkspace()
  store.companies = [
    { id: 'a', name: '삼성중공업' },
    { id: 'b', name: '엘앤에프' },
  ] as Company[]
  store.memos = [
    {
      id: 'a1',
      title: '삼성 메모',
      companyName: '삼성중공업',
      currentVersion: 1,
      versions: [{ version: 1 }],
    },
    {
      id: 'b1',
      title: '엘앤에프 메모',
      companyName: '엘앤에프',
      currentVersion: 1,
      versions: [{ version: 1 }],
    },
    { id: 'unknown', title: '미지정 메모', companyName: null, currentVersion: 1, versions: [] },
  ] as Memo[]
  const wrapper = mount(AnalysisLauncher, { props: { companyId: 'a' } })
  const options = () =>
    wrapper.findAll('select[aria-label="기준 메모"] option').map((o) => o.text())
  expect(options()).toEqual(['메모를 선택하세요', '삼성 메모'])
  await wrapper.get('select[aria-label="기준 메모"]').setValue('a1')
  await wrapper.setProps({ companyId: 'b' })
  expect(options()).toEqual(['메모를 선택하세요', '엘앤에프 메모'])
  expect((wrapper.get('select[aria-label="기준 메모"]').element as HTMLSelectElement).value).toBe(
    '',
  )
  wrapper.unmount()
})
