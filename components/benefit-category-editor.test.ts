/** @jest-environment jsdom */
import { createElement } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import BenefitCategoryEditor from './benefit-category-editor'

test('shows a failed save and blocks a duplicate in-flight benefit edit', async () => {
  const original = global.fetch
  let fail!: (value: Response) => void
  global.fetch = jest.fn(() => new Promise<Response>(resolve => { fail = resolve })) as typeof fetch
  const onChanged = jest.fn()
  try {
    render(createElement(BenefitCategoryEditor, {
      detail: { transaction_id: 'synthetic', automatic_benefit_category: 'SHOPPING_CREDIT',
        override_benefit_category: null, effective_benefit_category: 'SHOPPING_CREDIT',
        benefit_category_editable: true },
      options: [{ value: 'SHOPPING_CREDIT', label: 'Shopping' }, { value: 'DINING_CREDIT', label: 'Dining' }],
      onChanged,
    }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Benefit category' }), { target: { value: 'DINING_CREDIT' } })
    expect((screen.getByRole('combobox', { name: 'Benefit category' }) as HTMLSelectElement).disabled).toBe(true)
    expect(global.fetch).toHaveBeenCalledTimes(1)
    fail({ ok: false } as Response)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('could not be saved'))
    expect(onChanged).not.toHaveBeenCalled()
  } finally { global.fetch = original }
})
