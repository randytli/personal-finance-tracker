'use client'
import { useState } from 'react'
import { createClient } from '../../lib/supabase/browser.js'

export default function Login() {
  const supabase = createClient()
  const [step, setStep] = useState('password')
  const [status, setStatus] = useState('')
  const [factorId, setFactorId] = useState(null)

  async function signIn(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const { error } = await supabase.auth.signInWithPassword({
      email: String(form.get('email')), password: String(form.get('password')),
    })
    if (error) return setStatus(`sign-in failed: ${error.code ?? error.status}`)
    const { data, error: listError } = await supabase.auth.mfa.listFactors()
    const totp = data?.totp?.find((factor) => factor.status === 'verified')
    if (listError || !totp) return setStatus('no verified TOTP factor')
    setFactorId(totp.id)
    setStep('totp')
    setStatus('aal1 — enter the TOTP code')
  }

  async function verify(event) {
    event.preventDefault()
    const code = String(new FormData(event.currentTarget).get('code')).replace(/\s/g, '')
    const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code })
    if (error) return setStatus(`verify failed: ${error.code ?? error.status}`)
    window.location.assign('/probe')
  }

  async function routeCall() {
    const response = await fetch('/api/pft/probe/whoami', { cache: 'no-store' })
    setStatus(`route call: ${response.status}; upstream request id: ${response.headers.get('x-probe-request-id') ?? 'none'}`)
  }

  return (
    <main>
      <h1>M5 auth probe — sign in</h1>
      {step === 'password' ? (
        <form onSubmit={signIn}>
          <p><input name="email" type="email" autoComplete="username" placeholder="owner e-mail" required /></p>
          <p><input name="password" type="password" autoComplete="current-password" placeholder="password" required /></p>
          <button type="submit">Sign in</button>
        </form>
      ) : (
        <form onSubmit={verify}>
          <p><input name="code" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" required /></p>
          <button type="submit">Verify TOTP</button>
        </form>
      )}
      <p><button type="button" onClick={routeCall}>Call the route now (P1/P3/P5 evidence)</button></p>
      <p role="status">{status}</p>
    </main>
  )
}
