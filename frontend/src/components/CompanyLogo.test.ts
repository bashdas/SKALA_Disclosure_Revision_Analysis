import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CompanyLogo from './CompanyLogo.vue'
it('loads a domestic logo and falls back to the company initial on errors or unsupported codes', async () => {
  const wrapper = mount(CompanyLogo, { props: { code: '005930', name: '삼성전자' } })
  expect(wrapper.get('img').attributes('src')).toContain('Stock005930.png')
  await wrapper.get('img').trigger('load')
  expect(wrapper.classes()).toContain('has-image')
  await wrapper.get('img').trigger('error')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.text()).toBe('삼')
  await wrapper.setProps({ code: 'AAPL' })
  expect(wrapper.find('img').exists()).toBe(false)
  await wrapper.setProps({ code: '000660', name: 'SK하이닉스' })
  expect(wrapper.get('img').attributes('src')).toContain('Stock000660.png')
  wrapper.unmount()
})
