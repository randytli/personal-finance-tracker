/* Design-preview screenshots and network audit against a running preview (no interception).
 * PFT_CAPTURE_URL=http://127.0.0.1:3106/design-preview PFT_CAPTURE_OUT=/path node preview/capture.cjs
 * Fails if any browser request leaves the preview prefix or a CSP violation occurs.
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PFT_PLAYWRIGHT_MODULE || 'playwright')

const base = new URL(process.env.PFT_CAPTURE_URL || 'http://127.0.0.1:3106/design-preview')
assert(['127.0.0.1', 'localhost'].includes(base.hostname) && !['3000', '8000'].includes(base.port), 'Capture only an isolated local preview')
const prefix = base.pathname.replace(/\/$/, '')
const out = process.env.PFT_CAPTURE_OUT || path.join(__dirname, '.run', 'capture')
const widths = (process.env.PFT_CAPTURE_WIDTHS || '390,768,1440').split(',').map(Number)
fs.mkdirSync(out, { recursive: true })

function inPreview(url) {
  return url.origin === base.origin && (url.pathname === prefix || url.pathname.startsWith(prefix + '/'))
}

async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(400)
}

async function openDining(page, width) {
  const region = page.getByRole('region', { name: 'Net Spending by Category', exact: true })
  if (width < 768) await region.getByRole('button').filter({ hasText: 'Dining' }).first().click()
  else await region.getByRole('button', { name: /^Net Spending transactions for Dining:/ }).click()
  await settle(page)
}

async function main() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })
  const log = []
  try {
    for (const width of widths) for (const route of ['/', '/review', '/memberships']) {
      const phone = width < 768
      const page = await browser.newPage({ viewport: { width, height: phone ? 844 : 1000 }, ...(phone ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) })
      const errors = [], violations = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('request', request => log.push({ page: route, width, method: request.method(), url: request.url(), inPreview: inPreview(new URL(request.url())) }))
      await page.exposeFunction('__pftViolation', value => violations.push(value))
      await page.addInitScript(() => document.addEventListener('securitypolicyviolation', event => window.__pftViolation(`${event.violatedDirective} ${event.blockedURI}`)))
      await page.goto(base.href.replace(/\/$/, '') + (route === '/' ? '/' : route), { waitUntil: 'domcontentloaded' })
      await settle(page)
      const name = route === '/' ? 'overview' : route.slice(1)
      await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: true })
      const height = await page.evaluate(() => document.documentElement.scrollHeight)
      await page.screenshot({ path: path.join(out, `${name}-${width}-top.png`), fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(height, 2200) } })
      if (route === '/') {
        await openDining(page, width)
        await page.locator('#overview-transaction-details').evaluate(element => element.scrollIntoView({ block: 'start' }))
        await page.waitForTimeout(300)
        await page.screenshot({ path: path.join(out, `${name}-${width}-details.png`) })
      }
      if (route === '/review' || route === '/memberships') {
        await page.locator('main input[type=checkbox]').nth(2).check()
        await page.locator('[data-bulk-toolbar]').waitFor()
        await page.screenshot({ path: path.join(out, `${name}-${width}-selected.png`) })
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
      assert.equal(errors.length, 0, `${route}@${width} runtime errors: ${errors.join('; ')}`)
      assert.equal(violations.length, 0, `${route}@${width} CSP violations: ${violations.join('; ')}`)
      assert(overflow <= 0, `${route}@${width} horizontal overflow ${overflow}px`)
      console.log(JSON.stringify({ route, width, overflow, requests: log.filter(entry => entry.page === route && entry.width === width).length }))
      await page.close()
    }
  } finally { await browser.close() }
  const outside = log.filter(entry => !entry.inPreview)
  fs.writeFileSync(path.join(out, 'network-log.json'), JSON.stringify({ base: base.href, total: log.length, outside, requests: log }, null, 2))
  const paths = [...new Set(log.map(entry => new URL(entry.url).pathname.replace(/\/[^/]*\.(js|css|woff2)$/, '/*.$1').replace(/\?.*$/, '')))].sort()
  console.log(JSON.stringify({ totalRequests: log.length, outsidePreview: outside.length, distinctPaths: paths }, null, 1))
  assert.equal(outside.length, 0, 'Requests left the preview prefix: ' + outside.map(entry => entry.url).join(', '))
}
main().catch(error => { console.error(error); process.exitCode = 1 })
