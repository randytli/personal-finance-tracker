/* Bottom-of-page regression checks reuse M4's synthetic-only API harness. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium, webkit } = require(process.env.PFT_PLAYWRIGHT_MODULE || 'playwright')
const { fixture, routes, geometry, idle } = require('./pft_m4_browser_qa.cjs')
const { captureMobileLayout } = require('./pft_mobile_layout_probe.cjs')
const base = process.env.PFT_QA_URL || 'http://127.0.0.1:3003'
const out = process.env.PFT_QA_OUTPUT || '/tmp/pft-m4-bottom-20260930/browser'
const engineName = process.env.PFT_QA_ENGINE || 'chromium'
const engine = engineName === 'webkit' ? webkit : chromium
const nativeViewport = process.env.PFT_QA_NATIVE_VIEWPORT === '1'
fs.mkdirSync(out, { recursive: true })

async function bottom(page) {
 await page.waitForTimeout(100)
 for (let i = 0; i < 2; i++) {
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await page.waitForTimeout(50)
 }
 return page.evaluate(() => {
  const rect = element => { const r = element.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height } }
  const main = document.querySelector('main'), app = document.querySelector('.pft-app')
  const next = [...main.querySelectorAll('button')].find(button => button.textContent === 'Next')
  const bar = document.querySelector('[data-bulk-toolbar]')
  const spacer = document.querySelector('[data-bulk-spacer]')
  const style = getComputedStyle(main), bodyStyle = getComputedStyle(document.body)
  return { main: rect(main), app: rect(app), footer: rect(next.parentElement), next: rect(next),
   toolbar: bar ? rect(bar) : null, spacer: spacer ? rect(spacer) : null,
   pagePadding: parseFloat(style.paddingBottom), bodyPadding: parseFloat(bodyStyle.paddingBottom),
   documentHeight: document.documentElement.scrollHeight, scrollY, viewport: innerHeight, visibleHeight: visualViewport.height,
   closedBodies: [...main.querySelectorAll('article details:not([open]) > div')].map(element => ({ height: element.getBoundingClientRect().height, scrollHeight: element.scrollHeight })),
   rows: main.querySelectorAll('article').length }
 })
}
function naturalEnd(measured) {
 assert(!measured.toolbar && !measured.spacer, 'No unselected bulk spacer or toolbar')
 assert(Math.abs(measured.main.bottom - measured.footer.bottom - measured.pagePadding) <= 1, 'Content ends with its legitimate page padding')
 const expectedEnd = Math.max(measured.main.bottom + measured.scrollY, measured.viewport) + measured.bodyPadding
 assert(Math.abs(measured.documentHeight - expectedEnd) <= 2, 'No scroll extent after page/minimum viewport and safe area')
 for (const body of measured.closedBodies) assert.equal(body.height + body.scrollHeight, 0, 'Closed editors must have no layout or scroll extent')
}
function toolbarClearance(measured) {
 assert(measured.toolbar.top >= 0 && measured.toolbar.bottom <= measured.visibleHeight + 1, 'Toolbar fits visible viewport')
 assert(measured.next.top >= 0 && measured.next.bottom < measured.toolbar.top, 'Pagination Next remains reachable above toolbar')
 assert(measured.spacer.height > 0, 'Measured safe spacer remains while selected')
}

async function main() {
 const browser = await engine.launch({ headless: true, ...(engineName === 'chromium' ? { args: ['--no-sandbox'] } : {}) }), results = []
 try {
  const widths = process.env.PFT_QA_WIDTHS ? process.env.PFT_QA_WIDTHS.split(',').map(Number) : [320, 375, 390, 393, 430, 768, 1280, 1440, 844]
  for (const width of widths) for (const route of ['/review', '/memberships']) for (const count of [0, 3, 103]) {
   const phone = width < 768 || width === 844
   const page = await browser.newPage({ viewport: { width, height: width === 844 ? 390 : 844 }, ...(phone ? { isMobile: true, hasTouch: true } : {}) })
   const data = fixture(), errors = []
   page.on('pageerror', error => errors.push(error.message))
   data.review = data.review.slice(0, count); data.membership = data.membership.slice(0, count)
   if (!nativeViewport) await page.addInitScript(() => {
    const viewport = new EventTarget(); let forcedHeight = null
    Object.assign(viewport, { offsetTop: 0, scale: 1 })
    Object.defineProperties(viewport, { width: { get: () => innerWidth }, height: { get: () => forcedHeight ?? innerHeight, set: value => forcedHeight = value } })
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport })
   })
   await routes(page, data)
   await page.goto(base + route, { waitUntil: 'networkidle' }); await idle(page)
   const initial = await bottom(page)
   const measurements = { initial: await page.evaluate(captureMobileLayout) }
   naturalEnd(initial); await geometry(page, 'natural bottom', width)
   assert.equal(initial.rows, Math.min(count, phone ? 10 : 50), 'Responsive default page size')
   if (width === 390 || width === 1440) await page.screenshot({ path: path.join(out, `${engineName}-${route.slice(1)}-${width}-${count}-bottom.png`) })
   if (count) {
    if (width < 768) {
     const summary = page.locator('article details summary').last()
     await summary.click(); await bottom(page)
     await summary.click(); naturalEnd(await bottom(page))
    }
    await page.locator('main input[type=checkbox]').last().check()
    const bar = page.locator('[data-bulk-toolbar]'); await bar.waitFor()
    toolbarClearance(await bottom(page))
    measurements.selected = await page.evaluate(captureMobileLayout)
    await bar.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('restore_classification_auto')
    await bar.getByRole('button', { name: 'Review changes', exact: true }).click()
    toolbarClearance(await bottom(page))
    measurements.confirmation = await page.evaluate(captureMobileLayout)
    if (width < 768 && !nativeViewport) {
     await page.evaluate(() => { visualViewport.height = 340; visualViewport.dispatchEvent(new Event('resize')) })
     toolbarClearance(await bottom(page))
     await page.evaluate(() => { visualViewport.height = innerHeight; visualViewport.dispatchEvent(new Event('resize')) })
     toolbarClearance(await bottom(page))
    }
    await bar.getByRole('button', { name: phone && width < 640 ? 'Clear' : 'Clear selection', exact: true }).click()
    await bar.waitFor({ state: 'detached' }); naturalEnd(await bottom(page))
    measurements.cleared = await page.evaluate(captureMobileLayout)
    // Last partial page must also have a natural end and correct row counts.
    while (await page.getByRole('button', { name: 'Next', exact: true }).isEnabled()) {
     await page.getByRole('button', { name: 'Next', exact: true }).click(); await idle(page)
    }
    const last = await bottom(page); naturalEnd(last)
    assert.equal(last.rows, count % (phone ? 10 : 50) || (phone ? 10 : 50), 'Last page row count')
    measurements.lastPage = await page.evaluate(captureMobileLayout)
    await page.locator('main input[type=checkbox]').last().check()
    await bar.waitFor(); toolbarClearance(await bottom(page))
    measurements.lastPageSelected = await page.evaluate(captureMobileLayout)
    await bar.getByRole('button', { name: phone && width < 640 ? 'Clear' : 'Clear selection', exact: true }).click()
    await bar.waitFor({ state: 'detached' }); naturalEnd(await bottom(page))
   }
   if (engineName === 'chromium' && width === 390 && count === 103) {
    const client = await page.context().newCDPSession(page)
    await client.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: 47, bottom: 34, left: 0, right: 0 } })
    const padding = await page.evaluate(() => ({ top: getComputedStyle(document.body).paddingTop, bottom: getComputedStyle(document.body).paddingBottom }))
    assert.deepEqual(padding, { top: '47px', bottom: '34px' }, 'Nonzero safe-area CSS remains active')
    naturalEnd(await bottom(page))
    await page.locator('main input[type=checkbox]').last().check()
    await page.locator('[data-bulk-toolbar]').waitFor()
    const measured = await bottom(page); toolbarClearance(measured)
    assert(Math.abs(measured.toolbar.bottom - (measured.viewport - 34)) <= 1, 'Toolbar clears home-indicator inset')
    await page.locator('[data-bulk-toolbar]').getByRole('button', { name: 'Clear', exact: true }).click()
    naturalEnd(await bottom(page))
   }
   assert.equal(errors.length, 0, errors.join('; ')); assert.equal(data.writes.length, 0, 'No mutations needed for spacing QA')
   results.push({ engine: engineName, route, width, nativeViewport, listCount: count, rowsPerPage: phone ? 10 : 50, padding: initial.pagePadding, safeAreaEmulated: engineName === 'chromium' && width === 390 && count === 103, passed: true })
   fs.writeFileSync(path.join(out, `${engineName}-${route.slice(1)}-${width}-${count}-geometry.json`), JSON.stringify(measurements, null, 2))
   fs.writeFileSync(path.join(out, `${engineName}-results.json`), JSON.stringify(results, null, 2))
   console.log(JSON.stringify(results.at(-1)))
   await page.close()
  }
 } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
