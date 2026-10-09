import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import { publicConfig } from '../config.js'

const NO_STORE = 'private, no-store'

export async function updateSession(request) {
  let response = NextResponse.next({ request })
  let refreshed = false
  const { url, key } = publicConfig()
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        refreshed ||= cookiesToSet.some(({ name, value }) => name.includes('-auth-token') && value)
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
        response = NextResponse.next({ request })
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options))
        Object.entries(headers ?? {}).forEach(([name, value]) => response.headers.set(name, value))
      },
    },
  })
  // Do not run code between createServerClient and getClaims() (official guidance).
  const { data } = await supabase.auth.getClaims()
  if (!data?.claims && request.nextUrl.pathname.startsWith('/probe')) {
    const login = request.nextUrl.clone()
    login.pathname = '/login'
    const redirect = NextResponse.redirect(login)
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie))
    redirect.headers.set('Cache-Control', NO_STORE)
    return redirect
  }
  if (refreshed) response.headers.set('x-probe-mw-refresh', '1')
  response.headers.set('Cache-Control', NO_STORE)
  return response
}
