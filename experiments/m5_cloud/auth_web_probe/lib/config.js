export const PROJECT_REF = 'acyghoemtdrilsdszolq'

export function publicConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  if (url !== `https://${PROJECT_REF}.supabase.co` || !key?.startsWith('sb_publishable_')) {
    throw new Error('Supabase public configuration rejected')
  }
  return { url, key }
}
