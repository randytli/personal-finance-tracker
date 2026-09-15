import { bulkEditRequest, bulkErrorMessage } from './bulk-transaction-editor'

describe('bulk transaction editing helpers', () => {
  test('builds deterministic category and label requests', () => {
    expect(bulkEditRequest(['b', 'a'], 'set_category', 'GROCERIES')).toEqual({
      transaction_ids: ['a', 'b'], operation: 'set_category', category: 'GROCERIES',
    })
    expect(bulkEditRequest(['b', 'a'], 'exclude_label', 'CHINA')).toEqual({
      transaction_ids: ['a', 'b'], operation: 'exclude_label', label: 'CHINA',
    })
  })

  test('surfaces atomic validation reasons and counts', () => {
    expect(bulkErrorMessage({ detail: {
      message: 'Category editing requires included expense or refund transactions.',
      ineligible_count: 3,
    }})).toBe('Category editing requires included expense or refund transactions. (3)')
    expect(bulkErrorMessage({ detail: 'unsupported' })).toBe('unsupported')
  })
})
