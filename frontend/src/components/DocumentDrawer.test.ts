import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DocumentDrawer from './DocumentDrawer.vue'
import { useWorkspace } from '../stores/workspace'
import { services } from '../services'
import type { Memo } from '../types/domain'

vi.mock('../services', () => ({
  services: {
    memos: { edit: vi.fn() },
    reads: { mark: vi.fn(async () => 'read') },
  },
}))

it('edits the latest memo, retains drafts after errors and opens the saved version', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkspace()
  store.memos = [
    {
      id: 'memo',
      title: '메모',
      companyName: '기업',
      currentVersion: 1,
      versions: [{ version: 1, content: '기존 본문', createdAt: '2026-10-22' }],
    },
  ] as Memo[]
  const wrapper = mount(DocumentDrawer, { global: { plugins: [pinia] } })
  const dialog = wrapper.get('dialog').element as HTMLDialogElement
  dialog.showModal = () => dialog.setAttribute('open', '')
  dialog.close = () => dialog.removeAttribute('open')
  await store.openMemo('memo')
  await flushPromises()
  await wrapper.get('.memo-actions .button').trigger('click')
  await wrapper.get('textarea').setValue('수정 본문')
  vi.mocked(services.memos.edit).mockRejectedValueOnce(new Error('저장 실패'))
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('textarea').element.value).toBe('수정 본문')
  expect(wrapper.text()).toContain('저장 실패')
  vi.mocked(services.memos.edit).mockResolvedValueOnce({
    ...store.memos[0],
    currentVersion: 2,
    versions: [
      ...store.memos[0]!.versions,
      { version: 2, content: '수정 본문', createdAt: '2026-10-22' },
    ],
  } as Memo)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(services.memos.edit).toHaveBeenLastCalledWith('memo', '수정 본문', 1)
  expect(wrapper.find('textarea').exists()).toBe(false)
  expect(store.drawer?.selectedVersion).toBe(2)
  expect(store.memos[0]!.versions[0]!.content).toBe('기존 본문')
  await store.openMemo('memo', 1)
  await flushPromises()
  expect(wrapper.get('.memo-actions .button').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
