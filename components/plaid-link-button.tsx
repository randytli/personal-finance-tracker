'use client'

import { apiFetch } from '@/lib/api'
import { useCallback, useEffect, useState } from 'react'
import {
  usePlaidLink,
  type PlaidLinkOnExit,
  type PlaidLinkOnSuccess,
} from 'react-plaid-link'
import { Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import InstitutionBadge from '@/components/institution-badge'

const LINK_TOKEN_KEY = 'pft_plaid_link_token'

export default function PlaidLinkButton({ resumeOAuth = false }: { resumeOAuth?: boolean }) {
  const [linkToken, setLinkToken] = useState<string | null>(null)
  const [receivedRedirectUri, setReceivedRedirectUri] = useState<string | undefined>()
  const [shouldOpen, setShouldOpen] = useState(false)
  const [status, setStatus] = useState<string>('')
  const [items, setItems] = useState<Array<{ item_id: string; institution_name: string; status: string }>>([])

  useEffect(() => {
    if (resumeOAuth) return
    apiFetch('/api/pft/plaid/items')
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => setItems(Array.isArray(data.items) ? data.items : []))
      .catch(() => setStatus('Connected institutions could not be loaded.'))
  }, [resumeOAuth])

  useEffect(() => {
    if (!resumeOAuth) return
    const savedToken = window.localStorage.getItem(LINK_TOKEN_KEY)
      || window.sessionStorage.getItem(LINK_TOKEN_KEY)
    if (!savedToken) {
      setStatus('OAuth session not found. Return to the home page and start again.')
      return
    }
    setLinkToken(savedToken)
    setReceivedRedirectUri(window.location.href)
    setShouldOpen(true)
  }, [resumeOAuth])

  const onSuccess = useCallback<PlaidLinkOnSuccess>(async (publicToken, metadata) => {
    setStatus('Finishing secure connection…')
    try {
      const institution = metadata.institution
      if (!institution?.institution_id || !institution.name) {
        throw new Error('institution metadata missing')
      }
      const response = await apiFetch('/api/pft/plaid/exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          public_token: publicToken,
          institution_id: institution.institution_id,
          institution_name: institution.name,
        }),
      })
      if (!response.ok) throw new Error('exchange failed')
      window.localStorage.removeItem(LINK_TOKEN_KEY)
      window.sessionStorage.removeItem(LINK_TOKEN_KEY)
      setStatus('Institution saved as pending. Disable the Link gate, then sync and review it.')
    } catch {
      setStatus('Connection could not be saved. Check the local API logs and try again.')
    }
  }, [])

  const onExit = useCallback<PlaidLinkOnExit>((error) => {
    if (error) setStatus('Plaid Link closed with an error. No connection was saved.')
  }, [])

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess,
    onExit,
    receivedRedirectUri,
  })

  useEffect(() => {
    if (ready && shouldOpen) {
      setShouldOpen(false)
      open()
    }
  }, [open, ready, shouldOpen])

  async function startLink() {
    setStatus('Preparing Plaid Link…')
    try {
      const response = await apiFetch('/api/pft/plaid/link-token', { method: 'POST' })
      if (!response.ok) throw new Error('link token failed')
      const token = await response.json()
      if (typeof token !== 'string' || !token) throw new Error('invalid link token')
      window.localStorage.setItem(LINK_TOKEN_KEY, token)
      window.sessionStorage.removeItem(LINK_TOKEN_KEY)
      setLinkToken(token)
      setShouldOpen(true)
      setStatus('')
    } catch {
      setStatus('Plaid Link is unavailable. Confirm the local API and pilot gate.')
    }
  }

  return (
    <div className="space-y-3">
      {!resumeOAuth && (
        <>
          {items.length > 0 && (
            <ul aria-label="Connected institutions" className="flex flex-wrap gap-2 text-sm">
              {items.map((item) => <li key={item.item_id} className="inline-flex items-center gap-2 rounded-lg border bg-muted/40 py-1.5 pl-1.5 pr-2.5">
                <InstitutionBadge institutionName={item.institution_name} />
                <Badge variant={item.status === 'active' ? 'success' : 'warning'} className="capitalize">{item.status}</Badge>
              </li>)}
            </ul>
          )}
          <p className="text-sm text-muted-foreground">Choose your institution securely inside Plaid Link.</p>
          <Button type="button" variant="outline" onClick={startLink} disabled={shouldOpen}>
            <Plus aria-hidden="true" />Connect new institution
          </Button>
        </>
      )}
      {status && <p role="status" className="text-sm text-muted-foreground">{status}</p>}
    </div>
  )
}
