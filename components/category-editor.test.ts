import {
  categoryMutationRequest,
  mergeCategoryDetail,
  sortedCategoryOptions,
  type CategoryDetail,
} from './category-editor'
import { categoryMetadata, MANUAL_CATEGORY_VALUES } from './category-display'

describe('reusable category presentation and mutation helpers', () => {
  test('provides polished metadata for the full manual vocabulary and safe fallbacks', () => {
    for (const category of MANUAL_CATEGORY_VALUES) {
      const metadata = categoryMetadata(category)
      expect(metadata.label).not.toContain('_')
      expect(metadata.icon).toBeDefined()
    }
    expect(categoryMetadata('GENERAL_MERCHANDISE').label).toBe('General Merchandise')
    expect(categoryMetadata('FUTURE_CATEGORY').label).toBe('Future Category')
    expect(categoryMetadata(null).label).toBe('Uncategorized')
  })

  test('uses the existing PUT and DELETE category API semantics', () => {
    expect(categoryMutationRequest(null)).toEqual({ method: 'DELETE' })
    expect(categoryMutationRequest('GROCERIES')).toEqual({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category: 'GROCERIES' }),
    })
  })

  test('merges mutation results without replacing eligibility or other transaction fields', () => {
    const detail: CategoryDetail & { amount: string } = {
      transaction_id: 'transaction-1',
      original_category: 'GENERAL_MERCHANDISE',
      override_category: null,
      effective_category: 'GENERAL_MERCHANDISE',
      category_editable: true,
      amount: '-10.00',
    }
    const changed = {
      transaction_id: 'transaction-1',
      original_category: 'GENERAL_MERCHANDISE',
      override_category: 'GROCERIES',
      effective_category: 'GROCERIES',
    }
    expect(mergeCategoryDetail(detail, changed)).toEqual({
      ...detail,
      override_category: 'GROCERIES',
      effective_category: 'GROCERIES',
    })
    expect(mergeCategoryDetail(detail, { ...changed, transaction_id: 'other' })).toBe(detail)
  })

  test('sorts readable names with Uncategorized last', () => {
    expect(sortedCategoryOptions([
      { value: 'UNCATEGORIZED', label: 'Uncategorized' },
      { value: 'TRAVEL', label: 'Travel' },
      { value: 'BANK_FEES', label: 'Bank Fees' },
    ]).map(option => option.value)).toEqual(['BANK_FEES', 'TRAVEL', 'UNCATEGORIZED'])
  })
})
