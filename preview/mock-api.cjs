/* Design-preview synthetic API. Loopback only; no outbound requests, no Production data.
 *
 * Next.js rewrites /design-preview/api/pft/<x> to PFT_API_URL/<x>, so this server receives
 * backend-shaped paths (/analytics/..., /review/..., /sync/..., /plaid/...). Each request is
 * answered by the same in-memory responder the M4 browser harness uses, so the preview and
 * the harness share one fixture shape. Edits change only this process's memory.
 */
const http = require('node:http')

const host = '127.0.0.1'
const port = Number(process.env.PFT_PREVIEW_MOCK_PORT || 3107)
if (!Number.isInteger(port) || port < 1024 || [3000, 8000].includes(port)) throw Error('Refusing a Production or privileged port: ' + port)

// The harness rejects requests whose origin is not its base; give it this server's origin.
const origin = `http://${host}:${port}`
process.env.PFT_QA_URL = origin
const { fixture, routes } = require('../scripts/pft_m4_browser_qa.cjs')

// Readable synthetic merchants for design review. Row 0 keeps the harness's long/unbroken
// stress values; amounts vary so lists do not read as identical rows.
const merchants = ['Blue Bottle Coffee', 'Whole Foods Market', 'Delta Air Lines', 'Netflix', 'Sweetgreen', 'Uber',
  'Trader Joe’s', 'AMC Theatres', 'Marriott Bonvoy', 'Equinox', 'Apple Services', 'Shake Shack', 'Lyft', 'Spotify',
  'Hilton Honors', 'Costco Wholesale', 'Clear Secure', 'Resy', 'DoorDash', 'Saks Fifth Avenue']
function humanize(data) {
  for (const rows of [data.overview, data.review, data.membership]) rows.forEach((row, index) => {
    if (index === 0) return
    const merchant = merchants[index % merchants.length]
    const magnitude = (8 + ((index * 37.17) % 260)).toFixed(2)
    row.merchant_name = merchant
    row.description = `${merchant.toUpperCase()} ${String(4000 + index * 7).slice(-4)}`
    row.transaction_date = `2026-09-${String(28 - (index % 27)).padStart(2, '0')}`
    if (Number(row.amount) !== 0 && Math.abs(Number(row.amount)) < 1000) row.amount = Number(row.amount) < 0 ? '-' + magnitude : magnitude
  })
  return data
}

const data = humanize(fixture())
let respond
routes({ route: async (_pattern, handler) => { respond = handler } }, data)

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-PFT-Synthetic': '1' })
  res.end(typeof body === 'string' ? body : JSON.stringify(body))
}

const server = http.createServer((req, res) => {
  const chunks = []
  req.on('data', chunk => chunks.push(chunk))
  req.on('end', async () => {
    const incoming = new URL(req.url, origin)
    console.log(JSON.stringify({ at: new Date().toISOString(), method: req.method, path: incoming.pathname }))
    if (!/^\/(analytics|review|sync|plaid)\//.test(incoming.pathname)) return send(res, 404, { detail: 'Unknown preview API path' })
    // Plaid stays disabled: only the read-only item list is answered, and it is empty.
    if (incoming.pathname.startsWith('/plaid/') && !(req.method === 'GET' && incoming.pathname === '/plaid/items')) {
      return send(res, 403, { detail: 'Plaid is disabled in the design preview.' })
    }
    const body = Buffer.concat(chunks).toString('utf8')
    const url = new URL('/api/pft' + incoming.pathname + incoming.search, origin)
    let answered = false
    const route = {
      request: () => ({ url: () => url.href, method: () => req.method, postData: () => body || null, postDataJSON: () => JSON.parse(body) }),
      fulfill: ({ status, body: payload }) => { answered = true; send(res, status, payload) },
      continue: () => { answered = true; send(res, 404, { detail: 'Unknown preview API path' }) },
      abort: () => { answered = true; send(res, 404, { detail: 'Unknown preview API path' }) },
    }
    try { await respond(route) } catch (error) {
      if (!answered) send(res, 400, { detail: 'Synthetic preview request rejected: ' + error.message })
    }
  })
})
server.listen(port, host, () => console.log(`Synthetic preview API ready on ${origin}`))
