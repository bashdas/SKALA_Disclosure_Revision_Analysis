import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { toast } from 'vue-sonner'
import MemoUpload from './MemoUpload.vue'
import { useWorkspace } from '../stores/workspace'
import type { Memo } from '../types/domain'

vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
vi.mock('../services', () => ({ services: {} }))
afterEach(() => vi.restoreAllMocks())

it('opens upload and write tabs in a dialog and saves both modes to the selected company', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const upload = vi.spyOn(useWorkspace(), 'upload').mockResolvedValue({
    title: '기업 메모',
    companyName: '한화에어로스페이스',
  } as Memo)
  const wrapper = mount(MemoUpload, {
    props: { companyId: '00126566', companyName: '한화에어로스페이스' },
    global: { plugins: [pinia] },
  })
  const dialog = wrapper.get('dialog').element as HTMLDialogElement
  dialog.showModal = () => dialog.setAttribute('open', '')
  dialog.close = () => dialog.removeAttribute('open')
  await wrapper.get('button').trigger('click')
  expect(dialog.open).toBe(true)
  expect(wrapper.findAll('[role="tab"]')).toHaveLength(2)
  await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
  await wrapper.get('textarea').setValue('투자 가정')
  await wrapper.get('input[maxlength="500"]').setValue('작성한 메모')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(upload).toHaveBeenCalledWith(expect.any(File), '작성한 메모', '00126566')
  expect(toast.success).toHaveBeenCalledWith('메모를 추가했습니다.', { description: '기업 메모' })
  await wrapper.findAll('[role="tab"]')[0]!.trigger('click')
  const file = new File(['파일 메모'], 'research.txt', { type: 'text/plain' })
  Object.defineProperty(wrapper.get('input[type="file"]').element, 'files', { value: [file] })
  await wrapper.get('input[type="file"]').trigger('change')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(upload).toHaveBeenLastCalledWith(file, undefined, '00126566')
  await wrapper.get('[aria-label="메모 추가 닫기"]').trigger('click')
  expect(dialog.open).toBe(false)
  wrapper.unmount()
})
