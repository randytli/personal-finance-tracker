/* Institution lifecycle page QA with synthetic responses only; rejects Production ports. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PFT_PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.PFT_QA_URL || 'http://127.0.0.1:3007'
const target = new URL(base)
assert(['127.0.0.1', 'localhost'].includes(target.hostname) && target.port && target.port !== '3000', 'Use an isolated local frontend, never Production')
const out = process.env.PFT_QA_OUTPUT || '/tmp/pft-lifecycle-qa'
fs.mkdirSync(out, { recursive: true })

const long = 'ZELLE PAYMENT FROM A VERY LONG SYNTHETIC COUNTERPARTY NAME CONF# ABCD1234 '.repeat(2)
const cls = (type, internal, category = 'UNCATEGORIZED') => ({ transaction_type: type, is_spending: type === 'expense', is_internal_transfer: internal, category })
function fixture(status) {
  return {
    status, fail: new Set(), writes: [],
    checks: [
      { id: 'K1', label: 'Item can be activated', result: 'pass', detail: `Status is ${status}` },
      { id: 'K2', label: 'Consumer accounts discovered', result: 'pass', detail: '1 of 2 accounts are in consumer scope' },
      { id: 'K6', label: 'Normalization is complete', result: 'pass', detail: '42 rows; 0 missing or stale; 0 invalid source rows' },
      { id: 'K8', label: 'Sync health', result: 'warn', detail: 'metadata warning' },
      { id: 'K10', label: 'Date range', result: 'warn', detail: '2024-10-02 to 2026-09-30; starts before the published ledger (2025-01-03)' },
    ],
  }
}
const item = data => ({
  item_id: 'ally-item', institution_name: 'Ally Bank', status: data.status,
  sync_enabled: data.status !== 'deactivated', published: data.status !== 'pending',
  activated_at: null, deactivated_at: null, has_cursor: true, sync_paused: false, last_sync_success_at: null,
  metadata_warning: null, raw_transaction_count: 42, normalized_transaction_count: 42,
  accounts: [
    { account_id: 'b-check', name: 'Ally Spending Account With A Long Name', mask: '0001', type: 'depository', subtype: 'checking', consumer_transactions_enabled: true, transaction_count: 42 },
    { account_id: 'b-invest', name: 'Self-Directed Investing', mask: '0002', type: 'investment', subtype: 'brokerage', consumer_transactions_enabled: false, transaction_count: 0 },
  ],
})
const transactions = Array.from({ length: 12 }, (_, i) => ({
  transaction_id: `t${i}`, account_name: 'Ally Spending Account With A Long Name', transaction_date: `2026-09-${String(28 - i).padStart(2, '0')}`,
  amount: i === 0 ? '-12345678.99' : i % 3 ? '-42.10' : '1250.00', merchant_name: i === 1 ? 'LongMerchantReference'.repeat(6) : null,
  description: i === 0 ? long : `Synthetic posted transaction ${i}`, plaid_category: i % 3 ? 'FOOD_AND_DRINK' : 'TRANSFER_IN', transaction_type: null,
}))
const preview = {
  item_id: 'ally-item', transition: 'activate', digest: 'a'.repeat(64),
  summary_by_month: ['2026-07', '2026-08', '2026-09'].map(month => ({ month, metrics: {
    income: { before: '6550.00', after: '6475.00', delta: '-75.00' }, net_savings: { before: '2100.00', after: '2025.00', delta: '-75.00' },
    gross_spending: { before: '4450.00', after: '4492.10', delta: '42.10' }, net_spending: { before: '4450.00', after: '4492.10', delta: '42.10' } },
    categories: [{ category: 'DINING', before: '310.00', after: '352.10', delta: '42.10' }] })),
  new_transactions: transactions, removed_transactions: [],
  changed_existing_transactions: Array.from({ length: 6 }, (_, i) => ({
    transaction_id: `zin${i}`, item_id: 'chase', institution_name: 'Chase', account_name: 'Premier Plus Checking', transaction_date: `2026-0${3 + i}-15`,
    month: `2026-0${3 + i}`, amount: '75', merchant_name: null, description: i === 0 ? long : 'ZELLE PAYMENT FROM SAM CONF# ABCD1234', manual_type: false,
    before: cls('income', false), after: cls('transfer', true) })),
}

async function routes(page, data) {
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.origin !== base) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    const p = url.pathname.replace('/api/pft/plaid/items/ally-item', '')
    if (data.fail.has(p)) return reply({ detail: 'Synthetic read failure' }, 503)
    if (req.method() === 'POST') data.writes.push(p)
    if (p === '') return reply(item(data))
    if (p === '/transactions-preview') {
      const offset = Number(url.searchParams.get('offset')), limit = Number(url.searchParams.get('limit'))
      return reply({ total: transactions.length, transactions: transactions.slice(offset, offset + limit) })
    }
    if (p === '/activation-checks') return reply({ checks: data.checks })
    if (p === '/activation-preview') { await new Promise(resolve => setTimeout(resolve, 300)); return reply(preview) }
    if (p === '/reactivation-preview') return reply({ ...preview, digest: 'r'.repeat(64), summary_by_month: [], new_transactions: [], changed_existing_transactions: [] })
    if (p === '/reactivate') { data.status = 'active'; return reply({ status: 'active' }) }
    if (p === '/deactivation-preview') return reply({ ...preview, digest: 'd'.repeat(64), summary_by_month: [], new_transactions: [], changed_existing_transactions: [] })
    if (p === '/activate') { data.status = 'active'; return reply({ status: 'active' }) }
    if (p === '/deactivate') { data.status = 'deactivated'; return reply({ status: 'deactivated' }) }
    return reply({ detail: 'unexpected' }, 404)
  })
}

async function noHorizontalScroll(page, label) {
  const { scroll, width } = await page.evaluate(() => ({ scroll: document.scrollingElement.scrollWidth, width: window.innerWidth }))
  assert(scroll <= width, `${label}: horizontal scroll ${scroll} > ${width}`)
}

async function insideViewport(page, locator, label) {
  await locator.scrollIntoViewIfNeeded()
  const box = await locator.boundingBox(), size = page.viewportSize()
  assert(box && box.x >= 0 && box.x + box.width <= size.width + 0.5 && box.height >= 32, `${label}: ${JSON.stringify(box)}`)
}

const VIEWPORTS = [['mobile', 360, 740], ['tablet', 768, 1024], ['desktop', 1366, 900]]
const results = []
;(async () => {
  const browser = await chromium.launch()
  try {
    for (const [name, width, height] of VIEWPORTS) {
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, hasTouch: name === 'mobile' })
      const page = await context.newPage()
      const data = fixture('pending')
      await routes(page, data)
      await page.goto(`${base}/plaid/items/ally-item`)
      await page.getByRole('heading', { name: 'Ally Bank', level: 1 }).waitFor()
      await page.getByText('Normalization is complete').waitFor()
      await noHorizontalScroll(page, `${name} page`)
      assert.deepEqual(data.writes, [], 'loading the page wrote nothing')
      await page.screenshot({ path: path.join(out, `${name}-pending.png`), fullPage: true })

      const activate = page.getByRole('button', { name: 'Activate', exact: true })
      await insideViewport(page, activate, `${name} activate button`)
      await activate.click()
      const dialog = page.getByRole('dialog')
      await dialog.getByText('Calculating impact preview').waitFor({ state: 'attached' })
      await dialog.getByText('Existing transactions that change').waitFor()
      await noHorizontalScroll(page, `${name} dialog`)
      const overflowing = await dialog.evaluate(node => [...node.querySelectorAll('dd, li, p, span')]
        .filter(el => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow === 'visible' && el.clientWidth > 0)
        .map(el => el.textContent.slice(0, 40)))
      const clipped = await dialog.evaluate(node => { const box = node.getBoundingClientRect()
        return [...node.querySelectorAll('.money')].filter(el => { const r = el.getBoundingClientRect(); return r.right > box.right + 0.5 || r.left < box.left - 0.5 }).length })
      assert.equal(clipped, 0, `${name} dialog money outside the dialog`)
      const overlaps = await dialog.evaluate(node => { const cells = [...node.querySelectorAll('dl > div')].map(el => [el, el.getBoundingClientRect()])
        return cells.filter(([el, r]) => [...el.querySelectorAll('.money')].some(m => m.getBoundingClientRect().right > r.right + 0.5)).length })
      assert.equal(overlaps, 0, `${name} metric values overflow their cell (${overflowing.length} overflowing nodes)`)
      const dialogBox = await dialog.boundingBox()
      assert(dialogBox.x >= 0 && dialogBox.x + dialogBox.width <= width + 0.5 && dialogBox.height <= height + 0.5, `${name} dialog fits: ${JSON.stringify(dialogBox)}`)
      await page.screenshot({ path: path.join(out, `${name}-activate-dialog.png`) })
      const confirm = dialog.getByRole('button', { name: 'Confirm activation' })
      await insideViewport(page, confirm, `${name} confirm button`)
      await page.screenshot({ path: path.join(out, `${name}-activate-dialog-bottom.png`) })
      assert.deepEqual(data.writes, ['/activation-preview'], 'opening the dialog only previewed')

      // Keyboard: focus stays in the dialog and Escape closes it without writing.
      for (let i = 0; i < 6; i++) await page.keyboard.press('Tab')
      assert(await dialog.evaluate(node => node.contains(document.activeElement)), `${name} focus trapped`)
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'detached' })
      assert.deepEqual(data.writes, ['/activation-preview'])

      await activate.click()
      await page.getByRole('dialog').getByRole('button', { name: 'Confirm activation' }).click()
      await page.getByText('Institution activated.').waitFor()
      await page.getByRole('button', { name: 'Deactivate' }).waitFor()
      assert.deepEqual(data.writes, ['/activation-preview', '/activation-preview', '/activate'])

      await page.getByRole('button', { name: 'Deactivate' }).click()
      await page.getByRole('dialog').getByText(/No change: analytics/).waitFor()
      await page.screenshot({ path: path.join(out, `${name}-deactivate-dialog.png`) })
      await page.getByRole('dialog').getByRole('button', { name: 'Confirm deactivation' }).click()
      await page.getByRole('button', { name: 'Reactivate' }).waitFor()
      await noHorizontalScroll(page, `${name} deactivated`)
      await page.getByRole('button', { name: 'Reactivate' }).click()
      await page.getByRole('dialog').getByText(/No change: analytics/).waitFor()
      await page.screenshot({ path: path.join(out, `${name}-reactivate-dialog.png`) })
      await page.getByRole('dialog').getByRole('button', { name: 'Confirm reactivation' }).click()
      await page.getByText('Institution reactivated.').waitFor()
      assert.deepEqual(data.writes.slice(-4), ['/deactivation-preview', '/deactivate', '/reactivation-preview', '/reactivate'])

      // Failed check disables activation; read failures show a retryable error.
      const blocked = fixture('pending')
      blocked.checks.push({ id: 'K5', label: 'Initial sync completed', result: 'fail', detail: 'No transactions have been synced' })
      blocked.fail.add('/transactions-preview')
      const second = await context.newPage()
      await routes(second, blocked)
      await second.goto(`${base}/plaid/items/ally-item`)
      await second.getByText('Initial sync completed').waitFor()
      assert(await second.getByRole('button', { name: 'Activate', exact: true }).isDisabled(), `${name} blocked activation`)
      await second.getByText('The transaction preview could not be loaded.').waitFor()
      await noHorizontalScroll(second, `${name} blocked`)
      await second.screenshot({ path: path.join(out, `${name}-blocked-error.png`), fullPage: true })
      results.push({ viewport: `${name} ${width}x${height}`, ok: true })
      await context.close()
    }
  } finally {
    await browser.close()
  }
  console.log(JSON.stringify({ base, out, results }, null, 1))
})().catch(error => { console.error(error); process.exit(1) })
