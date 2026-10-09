// Disposable M5 owner-auth probe: forward one allowlisted operation to the pinned API preview
// (design §3 unit 2). Pure so node:test can cover it; the route handler supplies the access
// token only after getClaims() validated the session. Browser cookies are never forwarded.
export const OPERATIONS = new Set(['whoami'])
const API_PROJECT = 'pft-m5-auth-api-20261009'
const NO_STORE = { 'Cache-Control': 'private, no-store' }

export function upstreamFrom(env) {
  const url = new URL(env.M5_API_URL)
  if (url.protocol !== 'https:' || url.port || url.username || url.password || url.search ||
      url.hash || url.pathname !== '/' || url.hostname !== env.M5_API_HOST ||
      !url.hostname.endsWith('.vercel.app') || !url.hostname.startsWith(`${API_PROJECT}-`) ||
      (env.M5_API_PROTECTION_BYPASS || '').length < 32) {
    throw new Error('upstream pin rejected')
  }
  return { url, bypass: env.M5_API_PROTECTION_BYPASS }
}

function probeHeaders(result) {
  const headers = { ...NO_STORE }
  for (const [name, value] of result.headers) {
    if (name.startsWith('x-probe-')) headers[name] = value
  }
  return headers
}

export async function forward({ operation, accessToken, env, fetcher = fetch, timeoutMs = 15000 }) {
  if (!OPERATIONS.has(operation)) {
    return Response.json({ error: 'unknown operation' }, { status: 404, headers: NO_STORE })
  }
  if (typeof accessToken !== 'string' || accessToken.length === 0) {
    return Response.json({ error: 'not signed in' }, { status: 401, headers: NO_STORE })
  }
  let upstream
  try {
    upstream = upstreamFrom(env)
  } catch {
    return Response.json({ error: 'upstream rejected' }, { status: 503, headers: NO_STORE })
  }
  let result
  try {
    result = await fetcher(new URL(`/probe/${operation}`, upstream.url), {
      headers: { authorization: `Bearer ${accessToken}`, 'x-vercel-protection-bypass': upstream.bypass },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    return Response.json({ error: 'upstream unavailable' }, { status: 502, headers: NO_STORE })
  }
  const headers = probeHeaders(result)
  let body = null
  try {
    body = await result.json()
  } catch {
    body = null
  }
  if (result.status === 200 && body !== null && typeof body === 'object') {
    return Response.json(body, { status: 200, headers })
  }
  if ([401, 403, 503].includes(result.status)) {
    const reason = body && typeof body.error === 'string' ? body.error : 'rejected'
    return Response.json({ error: reason }, { status: result.status, headers })
  }
  return Response.json({ error: 'upstream failed', upstream_status: result.status }, { status: 502, headers })
}
