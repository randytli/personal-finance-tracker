/** @jest-environment jsdom */
import { createElement } from 'react'
import { render } from '@testing-library/react'
import AccountBadge, { accountBadgeStyle } from './account-badge'
import InstitutionBadge, { institutionBadgeStyle } from './institution-badge'

const accounts = [
  ['American Express', 'Gold', '3008', 'credit', 'AMEX GOLD · 3008', 'card'],
  ['American Express', 'Platinum Card', '1004', 'credit', 'AMEX PLATINUM · 1004', 'card'],
  ['Capital One', 'Venture X', '5082', 'credit', 'VENTURE X · 5082', 'card'],
  ['Chase', 'Freedom Flex', '6987', 'credit', 'FREEDOM FLEX · 6987', 'card'],
  ['Chase', 'Premier Plus Checking', '1106', 'depository', 'CHASE CHECKING · 1106', 'checking'],
  ['Chase', 'Savings', '3761', 'depository', 'CHASE SAVINGS · 3761', 'savings'],
  ['Bank of America', 'Adv Plus Banking Checking', '5041', 'depository', 'BOA CHECKING · 5041', 'checking'],
  ['Capital One', '360 Performance Savings', '9121', 'depository', 'CAPITAL ONE SAVINGS · 9121', 'savings'],
] as const

function rendered(container: HTMLElement) {
  const element = container.querySelector<HTMLElement>('[data-swatch]')!
  return { shape: element.dataset.swatch, hidden: element.getAttribute('aria-hidden') }
}

test('each known account keeps its label, gets its kind of swatch, and no two look the same', () => {
  const looks = accounts.map(([institutionName, accountName, accountMask, accountType, label, shape]) => {
    const { container } = render(createElement(AccountBadge, { institutionName, accountName, accountMask, accountType }))
    expect(container.textContent).toBe(label)
    expect(rendered(container)).toEqual({ shape, hidden: 'true' })
    return JSON.stringify(accountBadgeStyle({ institutionName, accountName, accountMask, accountType }).swatch)
  })
  expect(new Set(looks).size).toBe(accounts.length)
})

test('institutions keep their labels and have distinct swatches', () => {
  const looks = ['Chase', 'Bank of America', 'American Express', 'Capital One'].map(institutionName => {
    const { container } = render(createElement(InstitutionBadge, { institutionName }))
    expect(container.textContent).toBe(institutionName.toUpperCase())
    expect(rendered(container).hidden).toBe('true')
    return JSON.stringify(institutionBadgeStyle(institutionName).swatch)
  })
  expect(new Set(looks).size).toBe(4)
})
