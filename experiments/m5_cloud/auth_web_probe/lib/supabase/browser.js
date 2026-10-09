import { createBrowserClient } from '@supabase/ssr'
import { publicConfig } from '../config.js'

export function createClient() {
  const { url, key } = publicConfig()
  return createBrowserClient(url, key)
}
