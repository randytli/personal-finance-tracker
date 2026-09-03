/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiBaseUrl = process.env.PFT_API_URL || 'http://127.0.0.1:8000'
    return [
      {
        source: '/api/pft/plaid/:path*',
        destination: `${apiBaseUrl}/plaid/:path*`,
      },
      {
        source: '/api/pft/review/:path*',
        destination: `${apiBaseUrl}/review/:path*`,
      },
      {
        source: '/api/pft/analytics/:path*',
        destination: `${apiBaseUrl}/analytics/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
