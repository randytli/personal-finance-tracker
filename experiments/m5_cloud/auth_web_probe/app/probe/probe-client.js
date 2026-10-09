'use client'
import { useState } from 'react'
import { createClient } from '../../lib/supabase/browser.js'

const PROBE_HEADERS = ['x-probe-request-id', 'x-probe-instance', 'x-probe-db-connections',
  'x-probe-session-checks', 'x-probe-data-queries']

// Evidence entries hold statuses, reasons, counters and claim times only — never tokens.
function entry(event, response, body) {
  const result = { at: new Date().toISOString(), event, status: response.status, error: body?.error ?? null }
  for (const name of ['aal', 'iat', 'exp', 'seconds_until_exp', 'session_check', 'identity_ok', 'timings_ms']) {
    if (body && name in body) result[name] = body[name]
  }
  for (const name of PROBE_HEADERS) result[name.slice(8).replaceAll('-', '_')] = response.headers.get(name)
  return result
}

export default function ProbeClient({ rendered }) {
  const supabase = createClient()
  const [log, setLog] = useState([{ at: new Date().toISOString(), event: 'server-rendered', ...rendered }])

  async function whoami(event) {
    const response = await fetch('/api/pft/probe/whoami', { cache: 'no-store' })
    let body = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return entry(event, response, body)
  }

  async function once() {
    const result = await whoami('whoami')
    setLog((current) => [...current, result])
  }

  async function twice() {
    const results = await Promise.all([whoami('whoami-concurrent'), whoami('whoami-concurrent')])
    setLog((current) => [...current, ...results])
  }

  async function copy() {
    await navigator.clipboard.writeText(JSON.stringify(log, null, 2))
  }

  async function signOut() {
    await supabase.auth.signOut({ scope: 'global' })
    window.location.replace('/login') // full navigation discards client state
  }

  return (
    <main>
      <h1>M5 auth probe</h1>
      <p>
        <button type="button" onClick={once}>Fetch whoami</button>{' '}
        <button type="button" onClick={twice}>Fetch whoami ×2</button>{' '}
        <button type="button" onClick={copy}>Copy evidence JSON</button>{' '}
        <button type="button" onClick={signOut}>Sign out (global)</button>
      </p>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(log, null, 2)}</pre>
    </main>
  )
}
