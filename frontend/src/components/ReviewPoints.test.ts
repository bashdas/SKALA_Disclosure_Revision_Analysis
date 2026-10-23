import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ReviewPoints from './ReviewPoints.vue'
import type { Evidence, ReviewPoint } from '../types/domain'

const evidence: Evidence[] = [{ id: 'source-0', title: '공시 원문', quote: '달러 대금 지급일을 연기합니다.',
  kind: 'filing', location: '1쪽', url: 'https://dart.fss.or.kr/', publishedAt: '', context: '',
  documentId: 'filing:current', version: null, paragraph: null }]
const point: ReviewPoint = {
  perspectiveType: 'FX_HEDGE', title: '수취 일정과 헤지 만기 대응을 확인합니다.',
  viewType: 'DISCLOSURE_REVIEW', memoView: null,
  condition: '해당 달러 대금에 대한 환헤지를 보유한 경우입니다.',
  disclosureFact: '달러 대금 지급일이 연기됐습니다.', reason: '보유한 경우 만기를 대조해야 합니다.',
  question: '보유한 헤지의 만기와 금액이 수취 일정에 대응합니까?',
  checkItems: ['보유 여부와 만기 및 금액을 확인합니다.'], evidenceIds: ['source-0'],
}

it('새 관점은 공시 사실과 조건을 표시하고 메모 가정을 만들지 않으며 근거를 엽니다', async () => {
  const wrapper = mount(ReviewPoints, { props: { points: [point], evidence } })
  expect(wrapper.text()).toContain('새로운 검토 관점')
  expect(wrapper.find('.before-block').exists()).toBe(false)
  expect(wrapper.find('.after-block').text()).toContain(point.disclosureFact)
  expect(wrapper.find('.review-condition').text()).toContain(point.condition)
  expect(wrapper.text()).not.toContain('null')
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('openEvidence')?.[0]).toEqual([evidence[0]])
})

it('유형 없는 이전 관점은 기존 메모와 공시 비교를 유지하고 조건이 없으면 숨깁니다', () => {
  const { viewType: _, condition: __, ...legacy } = point
  const wrapper = mount(ReviewPoints, { props: { points: [{ ...legacy, memoView: '실제 메모 가정입니다.' }], evidence } })
  expect(wrapper.text()).toContain('기존 관점 재검토')
  expect(wrapper.find('.before-block').text()).toContain('실제 메모 가정입니다.')
  expect(wrapper.find('.review-condition').exists()).toBe(false)
})
