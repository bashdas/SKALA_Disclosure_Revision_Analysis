import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkspace } from './workspace'
import type { Company, Memo } from '../types/domain'
import { mount } from '@vue/test-utils'
import { services } from '../services'
import UiSelect from '../components/UiSelect.vue'
import AnalysisLauncher from '../components/AnalysisLauncher.vue'

vi.mock('../services', () => ({ services: { memos: { get: vi.fn() }, companies: { list: vi.fn() }, filings: { list: vi.fn(), invalidate: vi.fn() } } }))
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
  const wrapper = mount(AnalysisLauncher, { props: { companyId: 'a', filing: null } })
  const select = () => wrapper.findComponent(UiSelect)
  expect(select().props('options')).toEqual([{ value: 'a1', label: '삼성 메모' }])
  await select().setValue('a1')
  await wrapper.setProps({ companyId: 'b' })
  expect(select().props('options')).toEqual([{ value: 'b1', label: '엘앤에프 메모' }])
  expect(select().props('modelValue')).toBe('')
  wrapper.unmount()
})

it('shows a memo skeleton and does not reopen a drawer closed before loading finishes', async () => {
  const store = useWorkspace()
  let finish!: (value: Memo) => void
  vi.mocked(services.memos.get).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  const pending = store.openMemo('missing')
  expect(store.drawerLoading).toBe(true)
  expect(store.drawer?.title).toBe('메모')
  store.drawer = null
  finish({
    id: 'missing',
    title: '늦은 메모',
    currentVersion: 1,
    versions: [{ version: 1, content: '본문' }],
  } as Memo)
  await pending
  expect(store.drawer).toBeNull()
  expect(store.drawerLoading).toBe(false)
})

it('keeps company metadata when removing a favorite returns a filing-only company', async () => {
  const store = useWorkspace()
  store.companies = [{ id: 'a', name: '기업', code: '010140', sector: '조선', description: '기업 설명', favorite: true }] as Company[]
  vi.mocked(services.companies.list).mockResolvedValue([{ id: 'a', name: '기업', code: '', sector: '', description: '', favorite: false }] as Company[])
  vi.mocked(services.filings.list).mockResolvedValue([])
  await store.refresh()
  expect(store.companies[0]).toMatchObject({ code: '010140', sector: '조선', description: '기업 설명', favorite: false })
  vi.mocked(services.companies.list).mockResolvedValue([{ id: 'a', name: '기업', code: '005930', favorite: true }] as Company[])
  await store.refresh()
  expect(store.companies[0]).toMatchObject({ code: '005930', favorite: true })
})
