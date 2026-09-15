import {
  labelChoice,
  labelMutationRequest,
  mergeLabelDetail,
  type LabelDetail,
} from './label-editor'

const detail: LabelDetail = {
  transaction_id: 'transaction-1',
  automatic_labels: ['CHINA'],
  manual_label_decisions: { MEMBERSHIP: 'include', WORK: 'exclude' },
  effective_labels: ['CHINA', 'MEMBERSHIP'],
}

describe('reusable label state', () => {
  test('maps every label to its independent manual or automatic choice', () => {
    expect(labelChoice(detail, 'CHINA')).toBe('auto')
    expect(labelChoice(detail, 'MEMBERSHIP')).toBe('include')
    expect(labelChoice(detail, 'WORK')).toBe('exclude')
  })

  test('uses the existing PUT and DELETE label API semantics', () => {
    expect(labelMutationRequest('auto')).toEqual({ method: 'DELETE' })
    expect(labelMutationRequest('include')).toEqual({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: 'include' }),
    })
    expect(labelMutationRequest('exclude')).toEqual({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: 'exclude' }),
    })
  })

  test('merges label responses without replacing unrelated transaction fields', () => {
    const transaction = { ...detail, amount: '-12.34', effective_category: 'FOOD_AND_DRINK' }
    const changed: LabelDetail = {
      transaction_id: 'transaction-1',
      automatic_labels: ['CHINA'],
      manual_label_decisions: { CHINA: 'exclude' },
      effective_labels: [],
    }
    expect(mergeLabelDetail(transaction, changed)).toEqual({
      ...transaction,
      automatic_labels: ['CHINA'],
      manual_label_decisions: { CHINA: 'exclude' },
      effective_labels: [],
    })
    expect(mergeLabelDetail(transaction, { ...changed, transaction_id: 'other' })).toBe(transaction)
  })
})
