import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AnalysisPerspectives from './AnalysisPerspectives.vue'

it('선택과 미선택 이유를 세 관점 카드에 함께 표시합니다', () => {
  const wrapper = mount(AnalysisPerspectives, { props: { perspectives: [], decisions: [
    { type: 'FINANCE', selected: true, reason: '현금흐름 확인' },
    { type: 'INDUSTRY_CONTRACT', selected: false, reason: '계약 영향 없음' },
    { type: 'FX_HEDGE', selected: false, reason: '환율 영향 없음' },
  ] } })
  expect(wrapper.findAll('.perspective-card')).toHaveLength(3)
  for (const reason of ['현금흐름 확인', '계약 영향 없음', '환율 영향 없음']) expect(wrapper.text()).toContain(reason)
  expect(wrapper.findAll('.tag').map((tag) => tag.text())).toEqual(['미선택', '선택', '미선택'])
})
