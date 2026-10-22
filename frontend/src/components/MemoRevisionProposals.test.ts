import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MemoRevisionProposals from './MemoRevisionProposals.vue'
import type { Finding } from '../types/domain'

it('수정 제안 칸에 유지 판단을 표시하고 제목과 근거를 보존합니다', () => {
  const base = { id: 'one', beforeText: '기존 문장', newFact: '확인한 사실', reason: '판단 이유', suggestion: '', impactType: 'NO_IMPACT', evidenceIds: ['source'], memoParagraph: null } as Finding
  for (const finding of [base, { ...base, impactType: 'INTERPRETATION_REVIEW', suggestion: '기존  문장' }, { ...base, impactType: 'FACT_UPDATE', suggestion: '수정한 문장' }] as Finding[]) {
    const wrapper = mount(MemoRevisionProposals, { props: { findings: [finding], evidence: [{ id: 'source', title: '공시', quote: '원문', context: '원문', kind: 'filing', publishedAt: '2026-10-15', url: null, documentId: null, version: null, paragraph: null, location: '1쪽' }] } })
    expect(wrapper.get('h2').text()).toBe('메모수정 제안 1')
    expect(wrapper.findAll('.finding-explanation p')[1]!.text()).toBe(finding.impactType === 'FACT_UPDATE' ? '수정한 문장' : '기존 메모 문장을 유지합니다.')
    expect(wrapper.get('.evidence-chips button').text()).toContain('근거 1')
    wrapper.unmount()
  }
})
