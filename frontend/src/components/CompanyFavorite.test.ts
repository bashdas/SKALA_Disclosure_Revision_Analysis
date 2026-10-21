import { it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CompanyFavorite from './CompanyFavorite.vue'
import { useWorkspace } from '../stores/workspace'
import { favoriteCompany, removeFavorite } from '../services/catalog'
import type { Company } from '../types/domain'
vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/catalog', () => ({ favoriteCompany: vi.fn(), removeFavorite: vi.fn() }))
it('adds and removes the same company and preserves the state when the request fails', async () => {
  setActivePinia(createPinia())
  const store = useWorkspace()
  store.companies = [{ id: 'a', name: '기업', favorite: false }] as Company[]
  vi.spyOn(store, 'refresh').mockResolvedValue()
  const wrapper = mount(CompanyFavorite, { props: { companyId: 'a', name: '기업' } })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(favoriteCompany).toHaveBeenCalledWith('a')
  store.companies[0]!.favorite = true
  await flushPromises()
  expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
  vi.mocked(removeFavorite).mockRejectedValueOnce(new Error('요청 실패'))
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(removeFavorite).toHaveBeenCalledWith('a')
  expect(wrapper.get('[role="alert"]').text()).toBe('요청 실패')
  expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
  wrapper.unmount()
})
