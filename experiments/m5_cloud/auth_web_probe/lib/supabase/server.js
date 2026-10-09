import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { publicConfig } from '../config.js'

export async function createClient() {
  const cookieStore = await cookies()
  const { url, key } = publicConfig()
  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
        } catch {
          // Called from a Server Component; middleware.js writes refreshed cookies.
        }
      },
    },
  })
}
