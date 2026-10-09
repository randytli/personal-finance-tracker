import test from 'node:test'
import assert from 'node:assert/strict'
import { forward, upstreamFrom } from './forward.mjs'

const HOST = 'pft-m5-auth-api-20261009-abc123-pft2.vercel.app'
const env = { M5_API_URL: `https://${HOST}/`, M5_API_HOST: HOST, M5_API_PROTECTION_BYPASS: 'b'.repeat(32) }

function fake(make, calls = []) {
  const fetcher = async (url, init) => { calls.push({ url: String(url), init }); return make() }
  return { fetcher, calls }
}

test('unknown operation and missing token never call upstream', async () => {
  const { fetcher, calls } = fake(() => new Response('{}'))
  for (const [operation, accessToken, status] of [['admin', 't', 404], ['whoami', '', 401]]) {
    const result = await forward({ operation, accessToken, env, fetcher })
    assert.equal(result.status, status)
    assert.equal(result.headers.get('cache-control'), 'private, no-store')
  }
  assert.equal(calls.length, 0)
})

test('pins reject every other upstream', async () => {
  const bad = [
    { M5_API_URL: `http://${HOST}/` },
    { M5_API_URL: `https://${HOST}:8443/` },
    { M5_API_URL: `https://${HOST}/x` },
    { M5_API_URL: `https://${HOST}/?a=1` },
    { M5_API_URL: 'https://evil.example/', M5_API_HOST: 'evil.example' },
    { M5_API_URL: 'https://pft-m5-reader-20261001-x.vercel.app/', M5_API_HOST: 'pft-m5-reader-20261001-x.vercel.app' },
    { M5_API_PROTECTION_BYPASS: 'short' },
    { M5_API_URL: undefined },
  ]
  for (const change of bad) {
    assert.throws(() => upstreamFrom({ ...env, ...change }))
    const { fetcher, calls } = fake(() => new Response('{}'))
    const result = await forward({ operation: 'whoami', accessToken: 't', env: { ...env, ...change }, fetcher })
    assert.equal(result.status, 503)
    assert.equal(calls.length, 0)
  }
})

test('success passes the body and probe headers only', async () => {
  const { fetcher, calls } = fake(() => new Response(JSON.stringify({ kind: 'm5_auth_whoami', aal: 'aal2' }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-probe-request-id': 'r1', 'x-probe-db-connections': '1', 'set-cookie': 'a=b' },
  }))
  const result = await forward({ operation: 'whoami', accessToken: 'tok', env, fetcher })
  assert.equal(result.status, 200)
  assert.deepEqual(await result.json(), { kind: 'm5_auth_whoami', aal: 'aal2' })
  assert.equal(result.headers.get('x-probe-request-id'), 'r1')
  assert.equal(result.headers.get('x-probe-db-connections'), '1')
  assert.equal(result.headers.get('set-cookie'), null)
  assert.equal(result.headers.get('cache-control'), 'private, no-store')
  assert.equal(calls[0].url, `https://${HOST}/probe/whoami`)
  assert.deepEqual(Object.keys(calls[0].init.headers).sort(), ['authorization', 'x-vercel-protection-bypass'])
  assert.equal(calls[0].init.headers.authorization, 'Bearer tok')
  assert.equal(calls[0].init.redirect, 'error')
  assert.equal(calls[0].init.cache, 'no-store')
})

test('rejections pass through with their reason; other statuses become 502', async () => {
  for (const status of [401, 403, 503]) {
    const { fetcher } = fake(() => new Response(JSON.stringify({ error: 'session revoked' }), { status }))
    const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
    assert.equal(result.status, status)
    assert.deepEqual(await result.json(), { error: 'session revoked' })
  }
  const { fetcher } = fake(() => new Response('boom', { status: 500 }))
  const failed = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(failed.status, 502)
  assert.equal((await failed.json()).upstream_status, 500)
})

test('a 200 with a non-JSON body is never passed through', async () => {
  const { fetcher } = fake(() => new Response('<html>Vercel login</html>', { status: 200 }))
  const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(result.status, 502)
})

test('network errors, timeouts and redirects become 502', async () => {
  const fetcher = async () => { throw new TypeError('fetch failed: redirect mode is set to error') }
  const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(result.status, 502)
  assert.equal(result.headers.get('cache-control'), 'private, no-store')
})
