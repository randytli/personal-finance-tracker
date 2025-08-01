/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    appDir: true,
  },
  env: {
    SUPABASE_URL: process.env.SUPABASE_URL,
    SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY,
    PLAID_CLIENT_ID: process.env.PLAID_CLIENT_ID,
    PLAID_ENV: process.env.PLAID_ENV,
  },
}

module.exports = nextConfig
