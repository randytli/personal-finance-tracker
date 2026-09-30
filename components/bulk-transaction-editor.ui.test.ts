/** @jest-environment jsdom */
import { createElement } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import BulkTransactionEditor from './bulk-transaction-editor'

const base = {
  transactionIds: ['b', 'a'], categoryOptions: [{ value: 'GROCERIES', label: 'Groceries' }],
  benefitCategoryOptions: [{ value: 'SHOPPING_CREDIT', label: 'Shopping' }],
  labelOptions: [{ value: 'CHINA', label: 'China' }],
  allowClassification: true, allowCategory: true, allowBenefitCategory: true,
  classificationOptions: [{ value: 'reimbursement' as const, label: 'Reimbursement', eligibleCount: 2 }],
  onClear: jest.fn(),
}

test('confirms a value-free restore and invalidates confirmation after selection changes', async () => {
  const onApply = jest.fn(async () => true)
  const view = render(createElement(BulkTransactionEditor, { ...base, onApply }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk action' }), { target: { value: 'restore_category_auto' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review changes' }))
  expect(screen.getByText(/Restore category to Auto/)).toBeTruthy()
  view.rerender(createElement(BulkTransactionEditor, { ...base, transactionIds: ['a'], onApply }))
  expect(screen.queryByRole('button', { name: 'Apply to selected' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Review changes' }))
  fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))
  await waitFor(() => expect(onApply).toHaveBeenCalledWith({ transaction_ids: ['a'], operation: 'restore_category_auto' }))
})

test('blocks a mixed ineligible benefit set but permits benefit restore', () => {
  render(createElement(BulkTransactionEditor, { ...base, benefitIneligibleCount: 1, onApply: jest.fn(async () => true) }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk action' }), { target: { value: 'set_benefit_category' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk benefit category' }), { target: { value: 'SHOPPING_CREDIT' } })
  expect((screen.getByRole('button', { name: 'Review changes' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk action' }), { target: { value: 'restore_benefit_category_auto' } })
  expect((screen.getByRole('button', { name: 'Review changes' }) as HTMLButtonElement).disabled).toBe(false)
})

test('keeps confirmation after a failed save and accepts only one in-flight Apply', async () => {
  let finish!: (saved: boolean) => void
  const onApply = jest.fn(() => new Promise<boolean>(resolve => { finish = resolve }))
  render(createElement(BulkTransactionEditor, { ...base, onApply }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk action' }), { target: { value: 'restore_classification_auto' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review changes' }))
  const apply = screen.getByRole('button', { name: 'Apply to selected' })
  fireEvent.click(apply)
  fireEvent.click(apply)
  expect(onApply).toHaveBeenCalledTimes(1)
  finish(false)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Apply to selected' })).toBeTruthy())
})

test('fixed toolbar escapes clipped ancestors and shows the failed request beside confirmation', async () => {
  const clipped = document.createElement('div')
  clipped.style.overflow = 'hidden'
  document.body.appendChild(clipped)
  const view = render(createElement(BulkTransactionEditor, { ...base,
    errorMessage: 'Synthetic network failure; no changes saved.', onApply: jest.fn(async () => false),
  }), { container: clipped })
  expect(document.querySelector('[data-bulk-toolbar]')?.parentElement).toBe(document.body)
  expect(clipped.querySelector('[data-bulk-spacer]')).toBeTruthy()
  fireEvent.change(screen.getByRole('combobox', { name: 'Bulk action' }), { target: { value: 'restore_category_auto' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review changes' }))
  fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))
  await screen.findByText('Synthetic network failure; no changes saved.')
  expect(screen.getByRole('button', { name: 'Apply to selected' })).toBeTruthy()
  view.unmount()
  clipped.remove()
})

test('toolbar compensation counts existing page and safe-area padding once and clears on unmount', () => {
  const main = document.createElement('main')
  main.style.paddingBottom = '40px'
  const previousPadding = document.body.style.paddingBottom
  document.body.style.paddingBottom = '34px'
  document.body.appendChild(main)
  const view = render(createElement(BulkTransactionEditor, { ...base, onApply: jest.fn(async () => true) }), { container: main })
  const bar = document.querySelector('[data-bulk-toolbar]') as HTMLDivElement
  bar.style.bottom = '34px'
  bar.getBoundingClientRect = () => ({ height: 200 }) as DOMRect
  fireEvent(window, new Event('resize'))
  expect((main.querySelector('[data-bulk-spacer]') as HTMLElement).style.height).toBe('176px')
  view.unmount()
  expect(document.querySelector('[data-bulk-spacer]')).toBeNull()
  document.body.style.paddingBottom = previousPadding
  main.remove()
})
