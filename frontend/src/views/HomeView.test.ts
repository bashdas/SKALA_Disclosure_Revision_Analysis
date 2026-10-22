import { expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import HomeView from './HomeView.vue'
import { useWorkspace } from '../stores/workspace'
import type { Company } from '../types/domain'

vi.mock('../services', () => ({ services: {} }))
it('filters only favorites by company name or stock code and shows an empty search state', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useWorkspace().companies = [
    { id: 'a', name: '삼성전자', code: '005930', favorite: true },
    { id: 'b', name: 'SK하이닉스', code: '000660', favorite: true },
    { id: 'c', name: '삼성중공업', code: '010140', favorite: false },
  ] as Company[]
  const wrapper = mount(HomeView, {
    global: {
      plugins: [pinia],
      stubs: { MarketStrip: true, CompanyQuotesTable: true, RouterLink: true },
    },
  })
  const table = () => wrapper.findComponent({ name: 'CompanyQuotesTable' }).props('companies')
  const search = wrapper.get('input[aria-label="관심종목 검색"]')
  expect(table()).toHaveLength(2)
  await search.setValue('삼성')
  expect(table().map((c: Company) => c.id)).toEqual(['a'])
  await search.setValue('000660')
  expect(table().map((c: Company) => c.id)).toEqual(['b'])
  await search.setValue('없는 기업')
  expect(table()).toHaveLength(0)
  expect(wrapper.text()).toContain('검색 결과가 없습니다')
  await search.setValue('')
  expect(table()).toHaveLength(2)
  useWorkspace().visitCompany('b')
  await wrapper.vm.$nextTick()
  expect(table().map((c: Company) => c.id)).toEqual(['b', 'a'])
  wrapper.unmount()
})
