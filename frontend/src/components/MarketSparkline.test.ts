import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import MarketSparkline from './MarketSparkline.vue'

it.each([{ values: [100] }, { values: [100, 100, 100] }])(
  '단일 값·변화 없는 추이도 유한한 좌표로 표시한다: $values',
  ({ values }) => {
    const chart = mount(MarketSparkline, { props: { values, baseline: 100, label: '지수 추이' } })
    expect(chart.get('svg').attributes('aria-label')).toBe('지수 추이')
    for (const path of chart.findAll('path')) {
      expect(path.attributes('d')).not.toMatch(/NaN|Infinity/)
    }
  },
)
it.each([{ values: [] }, { values: [NaN, Infinity] }])(
  '유효한 추이가 없으면 가짜 그래프를 그리지 않는다: $values',
  ({ values }) => {
    const chart = mount(MarketSparkline, { props: { values, baseline: 100, label: '지수 추이' } })
    expect(chart.find('svg').exists()).toBe(false)
    expect(chart.text()).toBe('추이 자료 없음')
  },
)
