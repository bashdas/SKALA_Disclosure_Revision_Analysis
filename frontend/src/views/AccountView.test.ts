import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import AccountView from './AccountView.vue'
import { changePassword } from '../services/http'

vi.mock('../services/http', async () => {
  const { ref } = await import('vue')
  return {
    currentUser: ref({ email: 'user@example.com', role: 'ANALYST' }),
    changePassword: vi.fn(),
  }
})
it('opens account settings without a role label and validates password changes inside the modal', async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/home', component: { template: '<div />' } }],
  })
  await router.push('/home')
  const wrapper = mount(AccountView, { global: { plugins: [router] } })
  const dialog = wrapper.get('dialog').element as HTMLDialogElement
  dialog.showModal = () => dialog.setAttribute('open', '')
  dialog.close = () => dialog.removeAttribute('open')
  await wrapper.get('button').trigger('click')
  expect(dialog.open).toBe(true)
  expect(wrapper.text()).toContain('user@example.com')
  expect(wrapper.text()).not.toMatch(/권한|ANALYST/)
  const inputs = wrapper.findAll('input')
  await inputs[0]!.setValue('old-password')
  await inputs[1]!.setValue('new-password-123')
  await inputs[2]!.setValue('different')
  await wrapper.get('form').trigger('submit')
  expect(changePassword).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('새 비밀번호가 일치하지 않습니다.')
  await inputs[2]!.setValue('new-password-123')
  vi.mocked(changePassword).mockRejectedValue(new Error('현재 비밀번호를 확인해 주세요.'))
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(changePassword).toHaveBeenCalledWith('old-password', 'new-password-123')
  expect(dialog.open).toBe(true)
  expect(wrapper.text()).toContain('현재 비밀번호를 확인해 주세요.')
  await wrapper.get('[aria-label="내 계정 닫기"]').trigger('click')
  expect(dialog.open).toBe(false)
  expect((inputs[0]!.element as HTMLInputElement).value).toBe('')
  wrapper.unmount()
})
