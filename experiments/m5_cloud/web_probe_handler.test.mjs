import test from 'node:test';
import assert from 'node:assert/strict';
import { handleProbe } from './web_probe_handler.mjs';

const env = {
  M5_WEB_PROBE_TOKEN: 'w'.repeat(32),
  M5_VERCEL_PROJECT_NAME: 'pft-m5-web-probe-20261001',
  M5_READER_HOST: 'pft-m5-reader-20261001-synthetic.vercel.app',
  M5_READER_URL: 'https://pft-m5-reader-20261001-synthetic.vercel.app/',
  M5_READER_PROBE_TOKEN: 'r'.repeat(32),
  M5_READER_PROTECTION_BYPASS: 'b'.repeat(32),
};
const request = (operation = 'runtime', token = env.M5_WEB_PROBE_TOKEN) =>
  new Request(`https://example.invalid/api/probe?operation=${operation}`, {
    headers: { authorization: `Bearer ${token}` },
  });
const forbiddenFetch = () => { throw new Error('Unexpected network call'); };

test('unauthorized and invalid configuration cannot reach reader', async () => {
  assert.equal((await handleProbe(request('runtime', 'wrong'), env, forbiddenFetch)).status, 401);
  for (const override of [
    { DATABASE_URL: 'forbidden' }, { PLAID_SECRET: 'forbidden' },
    { M5_READER_PROTECTION_BYPASS: '' },
    { M5_READER_URL: 'https://production.example/' },
    { M5_READER_URL: `https://${env.M5_READER_HOST}:8443/` },
    { M5_READER_URL: `${env.M5_READER_URL}?redirect=1` },
  ]) {
    assert.equal((await handleProbe(request(), { ...env, ...override }, forbiddenFetch)).status, 503);
  }
  assert.equal((await handleProbe(request('sync'), env, forbiddenFetch)).status, 422);
});

test('server capability forwarded only to pinned probe; cookies and redirects excluded', async () => {
  const incoming = request('imports');
  incoming.headers.set('cookie', 'browser-session=discard');
  incoming.headers.set('x-vercel-protection-bypass', 'caller-value-must-not-forward');
  const result = await handleProbe(incoming, env, async (url, options) => {
    assert.equal(String(url), `${env.M5_READER_URL}probe/imports`);
    assert.equal(options.headers.authorization, `Bearer ${env.M5_READER_PROBE_TOKEN}`);
    assert.equal(options.headers['x-vercel-protection-bypass'], env.M5_READER_PROTECTION_BYPASS);
    assert.equal(options.headers.cookie, undefined);
    assert.equal(options.redirect, 'error');
    return Response.json({ all_ok: true }, { headers: { 'Set-Cookie': 'discard=true' } });
  });
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('Set-Cookie'), null);
  assert.equal(result.headers.get('Cache-Control'), 'private, no-store');
  const body = await result.text();
  assert.equal(JSON.parse(body).upstream.all_ok, true);
  assert.equal(body.includes(env.M5_READER_PROTECTION_BYPASS), false);
});

test('upstream failures suppress raw error text', async () => {
  const result = await handleProbe(request(), env, async () => new Response('private detail', { status: 500 }));
  assert.equal(result.status, 502);
  assert.equal((await result.text()).includes('private detail'), false);
});
