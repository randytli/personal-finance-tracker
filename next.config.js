/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiBaseUrl = process.env.PFT_API_URL || 'http://127.0.0.1:8000'
    return [
      {
        source: '/api/pft/plaid/link-token',
        destination: `${apiBaseUrl}/plaid/link-token`,
      },
      {
        source: '/api/pft/plaid/exchange',
        destination: `${apiBaseUrl}/plaid/exchange`,
      },
    ]
  },
}

module.exports = nextConfig
