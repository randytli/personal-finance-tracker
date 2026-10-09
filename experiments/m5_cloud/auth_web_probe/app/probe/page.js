import { redirect } from 'next/navigation'
import { createClient } from '../../lib/supabase/server.js'
import ProbeClient from './probe-client.js'

export const dynamic = 'force-dynamic'

export default async function Probe() {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  const claims = data?.claims
  if (!claims || claims.aal !== 'aal2') redirect('/login')
  return <ProbeClient rendered={{ aal: claims.aal, iat: claims.iat, exp: claims.exp }} />
}
