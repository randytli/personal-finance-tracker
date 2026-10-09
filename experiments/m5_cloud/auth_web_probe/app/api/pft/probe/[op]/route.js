import { createClient } from '../../../../../lib/supabase/server.js'
import { forward } from '../../../../../lib/forward.mjs'

export const dynamic = 'force-dynamic'
const NO_STORE = { 'Cache-Control': 'private, no-store' }

export async function GET(request, { params }) {
  const { op } = await params
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  const claims = data?.claims
  if (!claims) return Response.json({ error: 'not signed in' }, { status: 401, headers: NO_STORE })
  if (claims.aal !== 'aal2') return Response.json({ error: 'aal2 required' }, { status: 403, headers: NO_STORE })
  // The token is only forwarded; FastAPI makes the authorization decision.
  const { data: sessionData } = await supabase.auth.getSession()
  return forward({ operation: op, accessToken: sessionData?.session?.access_token ?? '', env: process.env })
}
