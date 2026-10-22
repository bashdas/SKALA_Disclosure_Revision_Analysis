import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import CompaniesView from './CompaniesView.vue'
import { request } from '../services/http'

vi.mock('../services/http', async () => {
  const { ref } = await import('vue')
  return { request: vi.fn(), currentUser: ref(null) }
})
vi.mock('../services', () => ({ services: {} }))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

it('uses global market-cap order, preserves the page snapshot, and resets on sort or search', async () => {
  vi.stubGlobal('innerHeight', -1000)
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  const api = vi.mocked(request)
  api.mockImplementation(async (url) => {
    const params = new URLSearchParams(String(url).split('?')[1])
    return {
      items: [
        {
          corp_code: params.get('offset') === '0' ? 'a' : 'b',
          company_name: '기업',
          stock_code: '005930',
        },
      ],
      total_count: 40,
      has_more: true,
      snapshot: 'a'.repeat(32),
    }
  })
  const wrapper = mount(CompaniesView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        CompanyQuotesTable: true,
        SkeletonState: true,
        UiSelect: {
          props: ['modelValue', 'options'],
          emits: ['update:modelValue'],
          template:
            '<select aria-label="기업 정렬" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="o in options" :value="o.value">{{o.label}}</option></select>',
        },
      },
    },
  })
  await flushPromises()
  expect(wrapper.get('h1').text()).toContain('기업')
  expect(wrapper.get('h1').text()).not.toContain('리서치')
  expect(String(api.mock.calls[0]![0])).toContain('sort=market_cap_desc')
  expect(String(api.mock.calls[0]![0])).not.toContain('seed=')
  await wrapper.get('.loading-state button').trigger('click')
  await flushPromises()
  expect(String(api.mock.lastCall![0])).toContain('offset=1')
  expect(String(api.mock.lastCall![0])).toContain('snapshot=' + 'a'.repeat(32))
  expect(wrapper.findComponent({ name: 'CompanyQuotesTable' }).props('companies')).toHaveLength(2)
  await wrapper.get('select').setValue('name')
  await flushPromises()
  expect(String(api.mock.lastCall![0])).toContain('sort=name')
  expect(String(api.mock.lastCall![0])).toContain('offset=0')
  expect(String(api.mock.lastCall![0])).not.toContain('snapshot=')
  expect(wrapper.findComponent({ name: 'CompanyQuotesTable' }).props('companies')).toHaveLength(1)
  await wrapper.get('input').setValue('005930')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(String(api.mock.lastCall![0])).toContain('query=005930')
  expect(String(api.mock.lastCall![0])).toContain('offset=0')
  wrapper.unmount()
})
