// Disposable server route only. This is a capability/routing probe, not owner Auth.
import { timingSafeEqual } from 'node:crypto';

function equal(left, right) {
  const a = Buffer.from(left), b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function handleProbe(request, env = process.env, fetcher = fetch) {
  const secret = env.M5_WEB_PROBE_TOKEN || '';
  const supplied = request.headers.get('authorization') || '';
  const headers = { 'Cache-Control': 'private, no-store' };
  if (secret.length < 32 || !equal(supplied, `Bearer ${secret}`)) {
    return Response.json({ error: 'Probe capability required' }, { status: 401, headers });
  }
  if (env.M5_VERCEL_PROJECT_NAME !== 'pft-m5-web-probe-20261001' ||
      env.PLAID_SECRET || env.PLAID_CLIENT_ID || env.PLAID_TOKEN_ENCRYPTION_KEY || env.DATABASE_URL) {
    return Response.json({ error: 'Probe configuration rejected' }, { status: 503, headers });
  }
  let upstream;
  try {
    upstream = new URL(env.M5_READER_URL);
    // Pin the exact newly deployed immutable reader hostname after creation.
    if (upstream.protocol !== 'https:' || upstream.port || upstream.username || upstream.password ||
        upstream.search || upstream.hash || upstream.pathname !== '/' ||
        upstream.hostname !== env.M5_READER_HOST || !upstream.hostname.endsWith('.vercel.app') ||
        !upstream.hostname.startsWith('pft-m5-reader-20261001-') ||
        (env.M5_READER_PROBE_TOKEN || '').length < 32 ||
        (env.M5_READER_PROTECTION_BYPASS || '').length < 32) throw new Error('pin');
  } catch {
    return Response.json({ error: 'Reader target rejected' }, { status: 503, headers });
  }
  const operation = new URL(request.url).searchParams.get('operation') || 'runtime';
  if (!['runtime', 'imports', 'connection'].includes(operation)) {
    return Response.json({ error: 'Unknown probe' }, { status: 422, headers });
  }
  const started = performance.now();
  try {
    const result = await fetcher(new URL(`/probe/${operation}`, upstream), {
      headers: { authorization: `Bearer ${env.M5_READER_PROBE_TOKEN}`,
                 'x-vercel-protection-bypass': env.M5_READER_PROTECTION_BYPASS },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(65000),
    });
    // Never forward Set-Cookie, redirect headers or a provider's raw error body.
    if (!result.ok) return Response.json({ error: 'Reader probe failed', upstream_status: result.status },
                                        { status: 502, headers });
    const data = await result.json();
    return Response.json({ kind: 'web_routing_probe', operation, wall_ms: performance.now()-started,
                           upstream: data }, { headers });
  } catch {
    return Response.json({ error: 'Reader request unavailable' }, { status: 502, headers });
  }
}
