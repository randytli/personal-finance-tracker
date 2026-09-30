/** @jest-environment jsdom */
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, renderHook } from '@testing-library/react'
import { TransactionTools, useTransactionPageSize } from './page-presentation'

const originalMatchMedia = window.matchMedia
let resize: (() => void) | undefined
let desktop = false

beforeEach(() => {
  desktop = false
  window.matchMedia = jest.fn(() => ({
    get matches() { return desktop },
    addEventListener: (_event: string, callback: () => void) => { resize = callback },
    removeEventListener: jest.fn(),
  })) as unknown as typeof window.matchMedia
})
afterEach(() => { cleanup(); window.matchMedia = originalMatchMedia; resize = undefined })

test('collapsed transaction tools remove editor bodies from layout and preserve unsaved input state', () => {
  const { container } = render(createElement(TransactionTools, { children: createElement('input', { defaultValue: 'draft' }) }))
  const disclosure = container.querySelector('details')!
  const body = disclosure.querySelector('div')!
  const input = body.querySelector('input')!
  expect(disclosure.open).toBe(false)
  expect(body.hidden).toBe(true)
  act(() => { disclosure.open = true; fireEvent(disclosure, new Event('toggle')) })
  expect(body.hidden).toBe(false)
  fireEvent.change(input, { target: { value: 'unsaved choice' } })
  act(() => { disclosure.open = false; fireEvent(disclosure, new Event('toggle')) })
  expect(body.hidden).toBe(true)
  act(() => { disclosure.open = true; fireEvent(disclosure, new Event('toggle')) })
  expect(body.hidden).toBe(false)
  expect(input.value).toBe('unsaved choice')
})

test('desktop breakpoint opens tools and mobile breakpoint removes their layout again', () => {
  const { container } = render(createElement(TransactionTools, { children: createElement('button', {}, 'Edit') }))
  const disclosure = container.querySelector('details')!
  const body = disclosure.querySelector('div')!
  act(() => { desktop = true; resize?.() })
  expect(disclosure.open).toBe(true)
  expect(body.hidden).toBe(false)
  act(() => { desktop = false; resize?.() })
  expect(disclosure.open).toBe(false)
  expect(body.hidden).toBe(true)
})

test('page size uses 10 for phones and touch landscape, and 50 for desktop', () => {
  const { result } = renderHook(() => useTransactionPageSize())
  expect(result.current).toBe(50)
  expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 767px), (pointer: coarse)')
  act(() => { desktop = true; resize?.() })
  expect(result.current).toBe(10)
  act(() => { desktop = false; resize?.() })
  expect(result.current).toBe(50)
})
