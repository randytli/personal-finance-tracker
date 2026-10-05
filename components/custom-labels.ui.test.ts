/** @jest-environment jsdom */
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import LabelManager from './label-manager'
import LabelEditor, { type LabelOption } from './label-editor'
import BulkTransactionEditor from './bulk-transaction-editor'

const options: LabelOption[] = [
  { value: 'CHINA', label: 'China', is_system: true, archived: false },
  { value: 'tech-id', label: 'tech', is_system: false, archived: false, color: 'success' },
  { value: 'old-id', label: 'old gear', is_system: false, archived: true },
]
const originalFetch = global.fetch
afterEach(() => { cleanup(); global.fetch = originalFetch })
async function click(element: HTMLElement) { await act(async () => { fireEvent.click(element) }) }

test('creates trimmed labels, reports duplicate errors, and refreshes shared options', async () => {
  const writes: Array<{ url: string; method?: string; body?: string }> = []
  global.fetch = jest.fn(async (input, init) => {
    writes.push({ url: String(input), method: init?.method, body: init?.body as string })
    return { ok: writes.length > 1, json: async () => writes.length === 1 ? { detail: 'A label with this name already exists.' } : options[1] } as Response
  })
  const refresh = jest.fn()
  window.addEventListener('pft-label-options-changed', refresh)
  try {
    render(createElement(LabelManager, { options }))
    await click(screen.getByRole('button', { name: 'Manage labels' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Label name' }), { target: { value: '  tech  ' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Label color' }), { target: { value: 'success' } })
    await click(screen.getByRole('button', { name: 'Create label' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'A label with this name already exists.')
    expect(writes[0]).toEqual({ url: '/api/pft/review/labels', method: 'POST', body: JSON.stringify({ name: 'tech', color: 'success' }) })
    await click(screen.getByRole('button', { name: 'Create label' }))
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    expect((screen.getByRole('textbox', { name: 'Label name' }) as HTMLInputElement).value).toBe('')
    expect(screen.queryByRole('button', { name: 'Rename China' })).toBeNull()
  } finally { window.removeEventListener('pft-label-options-changed', refresh) }
})

test('renames stable IDs and requires explicit archive confirmation', async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => options[1] } as Response))
  render(createElement(LabelManager, { options }))
  await click(screen.getByRole('button', { name: 'Manage labels' }))
  await click(screen.getByRole('button', { name: 'Rename tech' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Label name' }), { target: { value: 'Equipment' } })
  await click(screen.getByRole('button', { name: 'Save label' }))
  expect(global.fetch).toHaveBeenLastCalledWith('/api/pft/review/labels/tech-id', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ name: 'Equipment', color: 'success' }) }))
  await click(screen.getByRole('button', { name: 'Archive tech' }))
  expect(global.fetch).toHaveBeenCalledTimes(1)
  await click(screen.getByRole('button', { name: 'Confirm archive' }))
  expect(global.fetch).toHaveBeenLastCalledWith('/api/pft/review/labels/tech-id/archive', { method: 'POST' })
  expect(screen.queryByRole('button', { name: 'Archive old gear' })).toBeNull()
})

test('archived custom labels remain visible, disable include, and restore by DELETE', async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ transaction_id: 'tx', automatic_labels: ['CHINA'], manual_label_decisions: {}, effective_labels: ['CHINA'] }) } as Response))
  const onChanged = jest.fn()
  render(createElement(LabelEditor, { options, onChanged, detail: { transaction_id: 'tx', automatic_labels: ['CHINA'], manual_label_decisions: { 'old-id': 'include' }, effective_labels: ['CHINA', 'old-id'] } }))
  expect(screen.getByText('old gear')).toBeTruthy()
  await click(screen.getByRole('button', { name: 'Labels' }))
  const custom = screen.getByRole('combobox', { name: 'old gear label decision' })
  expect((within(custom).getByRole('option', { name: 'Add' }) as HTMLOptionElement).disabled).toBe(true)
  expect((within(custom).getByRole('option', { name: 'Remove' }) as HTMLOptionElement).disabled).toBe(false)
  expect(within(screen.getByRole('combobox', { name: 'China label decision' })).getByRole('option', { name: 'Auto' })).toBeTruthy()
  await act(async () => { fireEvent.change(custom, { target: { value: 'auto' } }) })
  expect(global.fetch).toHaveBeenLastCalledWith('/api/pft/review/transactions/tx/labels/old-id', expect.objectContaining({ method: 'DELETE' }))
  expect(onChanged).toHaveBeenCalledTimes(1)
})

test('bulk add excludes archived labels; remove and restore retain them', async () => {
  render(createElement(BulkTransactionEditor, { transactionIds: ['one', 'two'], categoryOptions: [], labelOptions: options, onApply: jest.fn(), onClear: jest.fn() }))
  const action = screen.getByRole('combobox', { name: 'Bulk action' })
  await act(async () => { fireEvent.change(action, { target: { value: 'include_label' } }) })
  expect(within(screen.getByRole('combobox', { name: 'Bulk label' })).queryByRole('option', { name: 'old gear' })).toBeNull()
  for (const operation of ['exclude_label', 'restore_label_auto']) {
    await act(async () => { fireEvent.change(action, { target: { value: operation } }) })
    expect(within(screen.getByRole('combobox', { name: 'Bulk label' })).getByRole('option', { name: 'old gear' })).toBeTruthy()
  }
})
