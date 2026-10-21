import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import StatusPill from './StatusPill.vue'

it('저장 실패를 완료와 다르게 표시한다', () => {
  const wrapper = mount(StatusPill, { props: { status: 'SAVE_FAILED' } })
  expect(wrapper.text()).toBe('저장 실패')
  expect(wrapper.classes()).toContain('save_failed')
  expect(wrapper.text()).not.toContain('완료')
})
