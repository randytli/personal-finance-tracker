/* Critical M4 flows use synthetic responses only; this script rejects Production ports. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const base = process.env.PFT_QA_URL || 'http://127.0.0.1:3003'
const target = new URL(base)
assert(['127.0.0.1', 'localhost'].includes(target.hostname) && target.port && target.port !== '3000', 'Use an isolated local frontend, never Production')
const out = process.env.PFT_QA_OUTPUT || '/tmp/pft-m4-20260930/browser'
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
const fixed = value => Number(value).toFixed(2)
const categories = ['DINING', 'GROCERIES', 'ENTERTAINMENT', 'UNCATEGORIZED', 'TRAVEL']
const common = { transaction_date: '2026-09-12', institution_id: 'synthetic-card-bank', institution_name: 'American Express', account_id: 'card', account_name: 'Platinum Card', account_mask: '1004', account_type: 'credit', account_subtype: 'credit card', is_internal_transfer: false, effective_is_internal_transfer: false, override_category: null, original_category: 'DINING', plaid_category: 'DINING', effective_category: 'DINING', automatic_benefit_category: null, override_benefit_category: null, effective_benefit_category: null, benefit_category_editable: false, override_transaction_type: null, automatic_labels: ['MEMBERSHIP'], effective_labels: ['MEMBERSHIP'], manual_label_decisions: {} }
function row(id, type, amount, index = 0) {
 return { ...common, manual_label_decisions: {}, automatic_labels: ['MEMBERSHIP'], effective_labels: ['MEMBERSHIP'], transaction_id: id, merchant_name: index === 0 ? 'LongMerchantReference'.repeat(10) : `Synthetic merchant ${index}`, description: `Synthetic posted transaction ${index} / ${'reference'.repeat(index === 0 ? 18 : 1)}`, amount: fixed(amount), transaction_type: type, effective_transaction_type: type, automatic_transaction_type: type, is_spending: type === 'expense', category_editable: type === 'expense' || type === 'refund' || type === 'reimbursement', benefit_category_editable: type === 'card_benefit', effective_benefit_category: type === 'card_benefit' ? 'DINING_CREDIT' : null, automatic_benefit_category: type === 'card_benefit' ? 'DINING_CREDIT' : null }
}
function sum(rows, predicate) { return fixed(rows.filter(predicate).reduce((total, r) => total + Math.abs(Number(r.amount)), 0)) }
function metrics(rows) {
 const gross = sum(rows, r => r.transaction_type === 'expense'), refunds = sum(rows, r => r.transaction_type === 'refund'), reimbursements = sum(rows, r => r.transaction_type === 'reimbursement'), benefits = sum(rows, r => r.transaction_type === 'card_benefit')
 return { gross_charges: gross, gross_spending: gross, refunds, reimbursements, unallocated_reimbursements: reimbursements, card_benefits: benefits, net_cost: fixed(Number(gross) - Number(refunds) - Number(reimbursements) - Number(benefits)), net_spending: fixed(Number(gross) - Number(refunds) - Number(reimbursements) - Number(benefits)), membership_transaction_count: rows.length, excluded_transaction_count: 0, unclassified_count: 0, reimbursement_transaction_count: rows.filter(r => r.transaction_type === 'reimbursement').length, unallocated_reimbursement_transaction_count: rows.filter(r => r.transaction_type === 'reimbursement').length }
}
function fixture() {
 const types = [...Array(65).fill('expense'), ...Array(5).fill('refund'), ...Array(5).fill('reimbursement'), ...Array(26).fill('card_benefit')]
 const overview = types.map((type, i) => row(`overview-${i}`, type, i === 0 ? -12345678.99 : type === 'expense' ? -200 : 20, i))
 overview.push({ ...row('negative-net', 'card_benefit', 25, 110), effective_category: 'ENTERTAINMENT', effective_benefit_category: 'ENTERTAINMENT_CREDIT' })
 const review = Array.from({ length: 120 }, (_, i) => row(`review-${i}`, null, i % 2 ? 20 : i === 0 ? -12345678.99 : -200, i))
 review.push({ ...row('confirmed-transfer', 'transfer', 300, 121), effective_is_internal_transfer: true })
 const membership = Array.from({ length: 110 }, (_, i) => row(`membership-${i}`, i < 70 ? 'expense' : i < 90 ? 'refund' : i < 100 ? 'card_benefit' : 'reimbursement', i < 70 ? i === 0 ? -12345678.99 : -200 : 20, i))
 for (const r of membership.filter(r => r.transaction_type === 'reimbursement')) Object.assign(r, { institution_id: 'synthetic-receiving-bank', institution_name: 'Chase', account_id: 'checking', account_name: 'Premier Plus Checking', account_mask: '1106', account_type: 'depository', account_subtype: 'checking' })
 return { overview, review, membership, requests: [], writes: [], fail: new Set(), empty: false, statusError: false, waitData: null }
}
async function routes(page, data) {
 await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url())
  if (url.origin !== base) return route.abort()
  if (!url.pathname.startsWith('/api/')) return route.continue()
  data.requests.push(url)
  const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (data.fail.has(url.pathname)) return reply({ detail: 'Synthetic read failure' }, 503)
  if (url.pathname.endsWith('/sync/status')) {
   if (data.statusError) return reply({}, 503)
   const date = new Date().toISOString()
   return reply({ last_published_run_id: 'synthetic-publication', published_at: date, current_run: { status: 'partial', started_at: date, error_category: null }, jobs: { status: 'running', heartbeat_at: date }, backup: { status: 'healthy', last_success_at: date, last_attempt_at: date, error_category: null }, institutions: [{ item_id: 'mock', institution_name: 'LongSyntheticBankName'.repeat(8), status: 'active', sync_paused: true, last_success_at: '2026-08-01T00:00:00Z', last_attempt_at: date, last_change_at: null, next_retry_at: date, metadata_warning: 'account-metadata-stale', latest_outcome: { status: 'failed', phase: 'fetch', error_category: 'connection-error', counts: { added_count: 0, modified_count: 0, removed_count: 0, classified_count: 0 } } }] })
  }
  if (req.method() !== 'GET') {
   data.writes.push({ method: req.method(), path: url.pathname, payload: req.postData() ? req.postDataJSON() : null })
   if (url.pathname.endsWith('/bulk-edit')) {
    const request = req.postDataJSON()
    for (const collection of [data.review, data.overview, data.membership]) for (const r of collection.filter(r => request.transaction_ids.includes(r.transaction_id))) {
     if (request.operation === 'set_classification') Object.assign(r, { transaction_type: request.transaction_type, effective_transaction_type: request.transaction_type, override_transaction_type: request.transaction_type, category_editable: true })
    }
    return reply({ changed_count: request.transaction_ids.length, unchanged_count: 0 })
   }
   const id = decodeURIComponent(url.pathname.split('/transactions/')[1]?.split('/')[0] || '')
   const r = [...data.overview, ...data.membership, ...data.review].find(r => r.transaction_id === id)
   assert(r, 'Synthetic mutation must target a mock row')
   if (url.pathname.endsWith('/category-override')) Object.assign(r, { override_category: req.method() === 'DELETE' ? null : req.postDataJSON().category, effective_category: req.method() === 'DELETE' ? r.original_category : req.postDataJSON().category })
   else if (url.pathname.endsWith('/benefit-category-override')) Object.assign(r, { override_benefit_category: req.method() === 'DELETE' ? null : req.postDataJSON().benefit_category, effective_benefit_category: req.method() === 'DELETE' ? r.automatic_benefit_category : req.postDataJSON().benefit_category })
   else if (url.pathname.includes('/labels/')) {
    const value = decodeURIComponent(url.pathname.split('/').at(-1)); const decision = req.method() === 'DELETE' ? 'auto' : req.postDataJSON().decision
    r.manual_label_decisions[value] = decision
    r.effective_labels = decision === 'exclude' ? r.effective_labels.filter(label => label !== value) : [...new Set([...r.effective_labels, value])]
   } else if (url.pathname.endsWith('/override')) Object.assign(r, { effective_transaction_type: req.method() === 'DELETE' ? r.automatic_transaction_type : req.postDataJSON().transaction_type, override_transaction_type: req.method() === 'DELETE' ? null : req.postDataJSON().transaction_type })
   else throw Error('Unmocked mutation path ' + url.pathname)
   return reply(r)
  }
  if (url.pathname.endsWith('/benefit-categories')) return reply({ categories: [{ value: 'DINING_CREDIT', label: 'Dining' }, { value: 'TRAVEL_CREDIT', label: 'Travel' }, { value: 'UNCATEGORIZED', label: 'Uncategorized' }] })
  if (url.pathname.endsWith('/categories')) return reply({ categories: categories.map(value => ({ value, label: value[0] + value.slice(1).toLowerCase() })) })
  if (url.pathname.endsWith('/labels')) return reply({ labels: [{ value: 'MEMBERSHIP', label: 'Membership' }] })
  if (url.pathname.endsWith('/plaid/items')) return reply({ items: [] })
  if (data.waitData) await data.waitData
  if (url.pathname.endsWith('/monthly')) {
   const rows = data.empty ? [] : data.overview, total = metrics(rows)
   const groups = categories.map(category => {
    const r = rows.filter(r => r.effective_category === category), m = metrics(r)
    return { ...m, category, expense_transaction_count: r.filter(r => r.transaction_type === 'expense').length, refund_transaction_count: r.filter(r => r.transaction_type === 'refund').length, reimbursement_transaction_count: r.filter(r => r.transaction_type === 'reimbursement').length, benefit_transaction_count: r.filter(r => r.transaction_type === 'card_benefit').length, contributing_transaction_count: r.length }
   })
   return reply({ ...total, month: url.searchParams.get('month'), income: '25000000.00', net_savings: fixed(25000000 - Number(total.net_spending)), category_net_breakdown: groups, unclassified_count: 120 })
  }
  if (url.pathname.endsWith('/trend')) return reply({ months: data.empty ? [] : Array.from({ length: 12 }, (_, i) => ({ month: new Date(Date.UTC(2025, 9 + i, 1)).toISOString().slice(0, 7), net_spending: fixed(12500000 + i * 100), income: '10000000.00', net_savings: fixed(-2500000 - i * 100) })) })
  if (url.pathname.endsWith('/breakdown')) return reply({ groups: data.empty ? [] : [{ ...metrics(data.overview), institution_id: 'synthetic-card-bank', institution_name: 'LongSyntheticBankName'.repeat(5) }] })
  if (url.pathname.endsWith('/memberships')) {
   const rows = data.empty ? [] : data.membership, total = metrics(rows)
   const accounts = ['card', 'checking'].map(id => { const r = rows.filter(r => r.account_id === id), m = metrics(r); return { ...common, ...r[0], ...m, account_id: id, net_cost: fixed(Number(m.gross_charges) - Number(m.refunds) - Number(m.card_benefits)) } })
   return reply({ period: url.searchParams.get('period'), end_month: url.searchParams.get('end_month'), start_month: url.searchParams.get('period') === 'ytd' ? url.searchParams.get('end_month').slice(0, 4) + '-01' : '2025-10', overall: total, accounts, type_counts: { charges: 70, refunds: 20, reimbursements: 10, card_benefits: 10 }, months: Array.from({ length: 12 }, (_, i) => ({ ...total, month: new Date(Date.UTC(2025, 9 + i, 1)).toISOString().slice(0, 7), net_cost: fixed(i === 11 ? -12345678.99 : 12500000 + i * 100) })) })
  }
  if (url.pathname.endsWith('/transactions')) {
   let rows
   if (url.pathname.includes('/review/')) {
    rows = data.review
    if (url.searchParams.get('mode') === 'needs_review') rows = rows.filter(r => r.override_transaction_type === null && !r.effective_is_internal_transfer)
    else {
     const direction = url.searchParams.get('direction'), kind = url.searchParams.get('transaction_type')
     rows = rows.filter(r => direction === 'all' || (direction === 'incoming') === (Number(r.amount) > 0))
     if (kind !== 'all') rows = rows.filter(r => (r.effective_transaction_type || 'unclassified') === kind)
    }
   } else if (url.searchParams.has('membership_view')) {
    rows = data.membership.filter(r => !url.searchParams.get('account_id') || r.account_id === url.searchParams.get('account_id'))
    const kind = { charges: 'expense', refunds: 'refund', card_benefits: 'card_benefit', reimbursements: 'reimbursement' }[url.searchParams.get('membership_view')]
    if (kind) rows = rows.filter(r => r.transaction_type === kind)
   } else {
    rows = data.overview.filter(r => !url.searchParams.get('canonical_category') || r.effective_category === url.searchParams.get('canonical_category'))
    const kind = { gross: 'expense', refunds: 'refund', reimbursements: 'reimbursement', card_benefits: 'card_benefit' }[url.searchParams.get('spending_component')]
    if (kind) rows = rows.filter(r => r.transaction_type === kind)
   }
   if (data.empty) rows = []
   const offset = Number(url.searchParams.get('offset')), limit = Number(url.searchParams.get('limit'))
   return reply({ transactions: rows.slice(offset, offset + limit), total: rows.length, component_totals: metrics(rows), membership_counts: { all: 110, charges: 70, refunds: 20, reimbursements: 10, card_benefits: 10 }, unallocated_reimbursements: metrics(rows).reimbursements, unallocated_reimbursement_transaction_count: rows.filter(r => r.transaction_type === 'reimbursement').length })
  }
  throw Error('Unmocked API path ' + url.pathname)
 })
}
async function geometry(page, label, width) {
 const measured = await page.evaluate(() => ({ viewport: innerWidth, scroll: document.documentElement.scrollWidth,
  small: [...document.querySelectorAll('.pft-app button, .pft-app a[href], .pft-app select, .pft-app input[type=month], .pft-app label:has(>input[type=checkbox]), [data-bulk-toolbar] button, [data-bulk-toolbar] select')].filter(el => { const r = el.getBoundingClientRect(); return r.height && r.width && (r.height < 43.5 || r.width < 43.5) }).map(el => el.getAttribute('aria-label') || el.textContent.trim().slice(0, 60)),
  smallText: [...document.querySelectorAll('.pft-app select, .pft-app input[type=month], [data-bulk-toolbar] select')].filter(el => el.getBoundingClientRect().height && parseFloat(getComputedStyle(el).fontSize) < 16).length,
  viewportMeta: document.querySelector('meta[name=viewport]').content, manifest: !!document.querySelector('link[rel=manifest]') }))
 assert(measured.scroll <= measured.viewport, `${label}: horizontal overflow ${JSON.stringify(measured)}`)
 assert(!measured.viewportMeta.includes('maximum-scale') && !measured.viewportMeta.includes('user-scalable=no') && measured.viewportMeta.includes('viewport-fit=cover'), 'Viewport preserves zoom and safe areas')
 assert(!measured.manifest, 'Do not advertise a missing manifest')
 if (width < 768 || width === 844) { assert.equal(measured.small.length, 0, label + ': small mobile targets ' + measured.small); assert.equal(measured.smallText, 0, label + ': mobile input text') }
}
async function idle(page) { await page.waitForTimeout(150); await page.waitForLoadState('networkidle') }
async function focusRefresh(page, data, match) {
 const previous = data.requests.length
 await page.evaluate(() => window.dispatchEvent(new Event('focus')))
 await page.waitForTimeout(150); await idle(page)
 assert(data.requests.length > previous, 'Focus refreshed data')
 const url = data.requests.filter(r => r.pathname.endsWith('/transactions')).at(-1)
 for (const [key, value] of Object.entries(match)) assert.equal(url.searchParams.get(key), value, 'Focus retained ' + key)
}
async function toolbar(page, width, data, classification) {
 const checks = page.locator('main input[type=checkbox]')
 await checks.last().check()
 await page.locator('[data-bulk-toolbar]').waitFor()
 await checks.last().uncheck()
 await checks.nth(Math.floor(await checks.count() / 2)).check()
 await page.locator('[data-bulk-toolbar]').waitFor()
 await checks.nth(Math.floor(await checks.count() / 2)).uncheck()
 await checks.nth(1).check()
 const bar = page.locator('[data-bulk-toolbar]'); await bar.waitFor()
 for (const where of ['top', 'middle', 'end']) {
  await page.evaluate(where => window.scrollTo(0, where === 'top' ? 0 : where === 'middle' ? document.documentElement.scrollHeight / 2 : document.documentElement.scrollHeight), where)
  const r = await bar.boundingBox(); assert(r.y >= 0 && r.y + r.height <= page.viewportSize().height + 1, 'Toolbar visible at ' + where)
 }
 await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('set_classification')
 await page.getByRole('combobox', { name: 'Bulk classification', exact: true }).selectOption(classification)
 await page.getByRole('button', { name: 'Review changes', exact: true }).click()
 await geometry(page, 'bulk confirmation', width)
 await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
 const next = await page.getByRole('button', { name: 'Next', exact: true }).boundingBox(), r = await bar.boundingBox()
 assert(next.y + next.height < r.y, 'Measured end spacer keeps pagination above toolbar')
 assert(await bar.evaluate(el => el.parentElement === document.body), 'Toolbar is outside clipped cards')
 if (width < 768) {
  await page.evaluate(() => { window.visualViewport.height = 340; window.visualViewport.dispatchEvent(new Event('resize')) })
  await page.waitForTimeout(100)
  const small = await bar.boundingBox(); assert(small.y >= 0 && small.y + small.height <= 341, 'Toolbar fits simulated keyboard visual viewport')
  await bar.evaluate(el => el.scrollTop = el.scrollHeight)
  await page.evaluate(() => { window.visualViewport.height = innerHeight; window.visualViewport.dispatchEvent(new Event('resize')) })
  await page.waitForTimeout(100)
 }
 const prior = data.writes.length
 await page.getByRole('button', { name: 'Apply to selected', exact: true }).click(); await idle(page)
 assert.equal(data.writes.length, prior + 1, 'One mock bulk mutation')
 await page.locator('[data-bulk-toolbar]').waitFor({ state: 'detached' })
}
async function openCategory(page, width, component = 'net') {
 const title = { net: 'Net Spending', gross: 'Gross Spending', card_benefits: 'Card Benefits' }[component]
 const region = page.getByRole('region', { name: title + ' by Category', exact: true })
 if (width < 768) await region.getByRole('button').filter({ hasText: 'Dining' }).click()
 else await region.getByRole('button', { name: new RegExp('^' + title + ' transactions for Dining:') }).click()
 await idle(page)
}
async function overviewFlow(page, data, width) {
 await page.getByLabel('Month', { exact: true }).fill('2026-08'); await idle(page)
 await openCategory(page, width)
 await page.getByRole('button', { name: 'Next', exact: true }).click(); await idle(page)
 await focusRefresh(page, data, { month: '2026-08', canonical_category: 'DINING', spending_component: 'net', offset: '100' })
 await page.getByRole('button', { name: 'Close', exact: true }).click()
 const trend = page.locator('.recharts-wrapper').first()
 if (width < 768) await trend.tap({ position: { x: 100, y: 120 } }); else await trend.hover({ position: { x: 100, y: 120 } })
 await page.locator('.recharts-tooltip-wrapper').first().waitFor({ state: 'visible' })
 await geometry(page, 'chart tooltip', width)
 await page.getByText('View monthly totals', { exact: true }).click()
 assert((await page.getByRole('list', { name: 'Monthly chart totals' }).textContent()).includes('-$'), 'Text chart alternative preserves negative values')
 if (width < 768) {
  await page.getByRole('button', { name: 'View full breakdown' }).click()
  const dialog = page.getByRole('dialog'); await dialog.waitFor()
  await dialog.locator('summary').filter({ hasText: 'Dining' }).click()
  await dialog.getByRole('button', { name: /^Card Benefits transactions for Dining:/ }).click(); await idle(page)
  await page.getByRole('dialog').waitFor({ state: 'detached' })
  await page.waitForFunction(() => document.activeElement?.id === 'overview-transaction-details', null, { timeout: 5000 })
 } else {
  await page.getByRole('button', { name: /^Card Benefits \$/ }).click(); await openCategory(page, width, 'card_benefits')
 }
 await page.getByRole('combobox', { name: 'Benefit category', exact: true }).first().selectOption('TRAVEL_CREDIT'); await idle(page)
 await page.getByRole('button', { name: 'Close', exact: true }).click()
 await page.getByRole('button', { name: /^Gross Spending \$/ }).click(); await openCategory(page, width, 'gross')
 await page.getByRole('button', { name: 'Edit category, currently Dining', exact: true }).first().click()
 await page.getByRole('radiogroup', { name: 'Spending category' }).getByText('Groceries', { exact: true }).click()
 await page.getByRole('button', { name: 'Save category', exact: true }).click(); await idle(page)
 assert(data.writes.some(r => r.path.endsWith('/category-override')) && data.writes.some(r => r.path.endsWith('/benefit-category-override')), 'Overview category and benefit flows completed')
 if (width < 768) {
  await page.locator('main input[type=checkbox]').nth(1).check()
  const bar = page.locator('[data-bulk-toolbar]'); await bar.waitFor()
  await page.getByRole('button', { name: 'View full breakdown' }).click()
  const dialog = page.getByRole('dialog'); await dialog.waitFor()
  assert(await dialog.evaluate(el => Number(getComputedStyle(el).zIndex)) > await bar.evaluate(el => Number(getComputedStyle(el).zIndex)), 'Category sheet stacks above bulk toolbar')
  assert(await dialog.evaluate(el => el.contains(document.activeElement)), 'Sheet traps initial keyboard focus')
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await dialog.waitFor({ state: 'detached' })
  await bar.getByRole('button', { name: 'Clear', exact: true }).click()
 }
}
async function reviewFlow(page, data, width) {
 await page.getByRole('button', { name: 'Next', exact: true }).click(); await idle(page)
 await focusRefresh(page, data, { mode: 'needs_review', limit: width < 768 || width === 844 ? '10' : '50', offset: width < 768 || width === 844 ? '10' : '50' })
 await toolbar(page, width, data, 'expense')
 await page.getByRole('button', { name: 'Credits & Transfers', exact: true }).click(); await idle(page)
 await page.getByRole('combobox', { name: 'Effective type filter', exact: true }).selectOption('unclassified'); await idle(page)
 await focusRefresh(page, data, { mode: 'credits_transfers', direction: 'incoming', transaction_type: 'unclassified', offset: '0' })
 await toolbar(page, width, data, 'reimbursement')
 await page.getByRole('combobox', { name: 'Direction filter', exact: true }).selectOption('outgoing'); await idle(page)
 const first = page.locator('article').first()
 if (width < 768) await first.locator('summary').click()
 await first.getByRole('combobox', { name: /Classification for/ }).selectOption('expense')
 await first.getByRole('button', { name: 'Save', exact: true }).click(); await idle(page)
}
async function membershipFlow(page, data, width) {
 const trend = page.locator('.recharts-wrapper').first()
 if (width < 768) await trend.tap({ position: { x: 100, y: 120 } }); else await trend.hover({ position: { x: 100, y: 120 } })
 await page.locator('.recharts-tooltip-wrapper').first().waitFor({ state: 'visible' })
 await geometry(page, 'Membership chart tooltip', width)
 await page.getByRole('combobox', { name: /^Period/ }).selectOption('ytd'); await idle(page)
 await page.getByLabel('Ending month', { exact: true }).fill('2026-08'); await idle(page)
 await page.getByRole('button', { name: /^AMEX PLATINUM/ }).click(); await idle(page)
 await page.getByRole('button', { name: 'Next', exact: true }).click(); await idle(page)
 await focusRefresh(page, data, { start_month: '2026-01', end_month: '2026-08', account_id: 'card', membership_view: 'all', limit: width < 768 || width === 844 ? '10' : '50', offset: width < 768 || width === 844 ? '10' : '50' })
 await page.getByRole('button', { name: /^Card Benefits \(/ }).click(); await idle(page)
 const first = page.locator('article').first(); if (width < 768) await first.locator('summary').click()
 // The save reloads and remounts rows; wait for that reload, not a fixed delay.
 const reloaded = page.waitForResponse(response => response.url().includes('/analytics/transactions'))
 await first.getByRole('combobox', { name: 'Benefit category', exact: true }).selectOption('TRAVEL_CREDIT'); await reloaded; await idle(page)
 const changed = page.locator('article').first(); if (width < 768 && await changed.locator('details').getAttribute('open') === null) await changed.locator('summary').click()
 await changed.getByRole('button', { name: 'Labels', exact: true }).click()
 await changed.getByRole('combobox', { name: 'Membership label decision', exact: true }).selectOption('include'); await idle(page)
 await page.getByRole('button', { name: 'View reimbursements received', exact: true }).click(); await idle(page)
 assert((await page.locator('main').textContent()).includes('receiving account'), 'Reimbursement context remains truthful')
 await page.getByText('View monthly totals', { exact: true }).click()
 assert((await page.getByRole('list', { name: 'Monthly chart totals' }).textContent()).includes('-$12,345,678.99'), 'Membership text totals preserve negative values')
 assert(data.writes.some(r => r.path.endsWith('/benefit-category-override')) && data.writes.some(r => r.path.includes('/labels/')), 'Membership benefit and label edits completed')
}
async function states(page, data, route, width) {
 data.fail.add(route === '/' ? '/api/pft/analytics/monthly' : route === '/review' ? '/api/pft/review/transactions' : '/api/pft/analytics/memberships')
 await page.reload({ waitUntil: 'networkidle' }); await page.getByRole('button', { name: 'Retry loading', exact: true }).waitFor()
 data.fail.clear(); await page.getByRole('button', { name: 'Retry loading', exact: true }).click(); await idle(page)
 assert.equal(await page.locator('main [role=alert]').count(), 0, 'Read retry recovers without mutation')
 data.statusError = true; await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await idle(page)
 await page.getByRole('button', { name: 'Retry status', exact: true }).waitFor()
 assert(!(await page.locator('main').textContent()).includes('· All clear'), 'Status failure cannot claim all-clear')
 data.statusError = false; await page.getByRole('button', { name: 'Retry status', exact: true }).click(); await idle(page)
 data.empty = true; await page.getByRole('button', { name: 'Retry loading', exact: true }).click(); await idle(page)
 if (route !== '/') await page.getByText(route === '/review' ? 'Nothing needs review.' : 'No matching transactions.', { exact: true }).waitFor()
 await geometry(page, 'empty/error/recovery', width)
}
async function main() {
 // Lazy so the synthetic fixtures can be reused without Playwright installed.
 const { chromium, webkit } = require(process.env.PFT_PLAYWRIGHT_MODULE || 'playwright')
 fs.mkdirSync(out, { recursive: true })
 const engine = process.env.PFT_QA_ENGINE === 'webkit' ? webkit : chromium
 const browser = await engine.launch({ headless: true, ...(engine === chromium ? { args: ['--no-sandbox'] } : {}) }), results = []
 try {
  const widths = process.env.PFT_QA_WIDTHS ? process.env.PFT_QA_WIDTHS.split(',').map(Number) : [320, 375, 390, 393, 430, 768, 1280, 1440, 844]
  for (const width of widths) for (const route of ['/', '/review', '/memberships']) {
   const page = await browser.newPage({ viewport: { width, height: width === 844 ? 390 : 950 }, ...(width < 768 || width === 844 ? { isMobile: true, hasTouch: true } : {}) }), data = fixture(), errors = []
   page.on('pageerror', e => errors.push(e.message))
   await page.addInitScript(() => {
    const viewport = new EventTarget(); let forcedHeight = null
    Object.assign(viewport, { offsetTop: 0, scale: 1 })
    Object.defineProperties(viewport, { width: { get: () => innerWidth }, height: { get: () => forcedHeight ?? innerHeight, set: value => forcedHeight = value } })
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport })
   })
   await routes(page, data)
   let release; data.waitData = new Promise(resolve => release = resolve)
   await page.goto(base + route, { waitUntil: 'domcontentloaded' })
   await page.getByText(route === '/' ? 'Loading analytics…' : route === '/review' ? 'Loading transactions…' : 'Loading membership costs…', { exact: true }).waitFor()
   release(); data.waitData = null; await idle(page)
   await geometry(page, 'initial ' + route, width)
   const health = page.getByRole('region', { name: 'Sync and backup health', exact: true })
   await health.locator('summary').first().click(); await health.locator('summary').nth(1).click(); await geometry(page, 'expanded health', width)
   await health.locator('summary').first().click()
   await page.screenshot({ path: path.join(out, `${route === '/' ? 'overview' : route.slice(1)}-${width}.png`) })
   if (route === '/') await overviewFlow(page, data, width)
   if (route === '/review') await reviewFlow(page, data, width)
   if (route === '/memberships') await membershipFlow(page, data, width)
   await geometry(page, 'flow completed ' + route, width)
   await page.screenshot({ path: path.join(out, `${route === '/' ? 'overview' : route.slice(1)}-${width}-flow.png`) })
   if (width === 393 || width === 1440) await states(page, data, route, width)
   assert.equal(errors.length, 0, 'No runtime errors: ' + errors.join('; '))
   results.push({ route, width, height: page.viewportSize().height, passed: true, mockWrites: data.writes.length, checks: ['overflow', 'mobile targets and text', 'safe-area/zoom metadata', 'loading', 'sync warnings', 'focus/range/filter/page preservation', 'complete page flow', ...(route === '/review' ? ['bulk top/middle/end', 'pagination clear of toolbar', ...(width < 768 ? ['simulated keyboard visual viewport'] : []), 'both Review modes'] : []), ...((width === 393 || width === 1440) ? ['empty', 'read errors and retry', 'API status recovery'] : [])] })
   fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2)); console.log(JSON.stringify(results.at(-1)))
   await page.close()
  }
 } finally { await browser.close() }
}
module.exports = { fixture, routes, geometry, idle }
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1 })
