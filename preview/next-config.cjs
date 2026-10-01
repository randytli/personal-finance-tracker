/* Design-preview build settings. Loaded by next.config.js only when PFT_PREVIEW_BASE_PATH is set,
 * so Production builds never see basePath, the separate distDir, the Plaid stub or this CSP.
 */
const path = require('node:path')

const BASE_PATH = '/design-preview'
const PREVIEW_ORIGINS = ['http://127.0.0.1:3106', 'http://localhost:3106', 'https://pft-host.tailc4d964.ts.net']

function assertPreviewApi(value) {
  // Fail closed: rewrites are baked in at build time, so a missing or non-mock target must stop the build.
  if (!value) throw Error('Design preview requires PFT_API_URL to point at the local synthetic mock.')
  const url = new URL(value)
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || ['3000', '8000'].includes(url.port)) {
    throw Error(`Design preview refuses API target ${value}; use the loopback synthetic mock.`)
  }
}

module.exports = function withDesignPreview(config) {
  if (process.env.PFT_PREVIEW_BASE_PATH !== BASE_PATH) throw Error(`PFT_PREVIEW_BASE_PATH must be ${BASE_PATH}`)
  assertPreviewApi(process.env.PFT_API_URL)
  // Exact base path (root RSC prefetch) plus everything below it; nothing else on the origin.
  const connect = PREVIEW_ORIGINS.flatMap(origin => [`${origin}${BASE_PATH}`, `${origin}${BASE_PATH}/`]).join(' ')
  const policy = [
    "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "font-src 'self' data:", `connect-src ${connect}`, "form-action 'none'",
    "base-uri 'none'", "object-src 'none'", "worker-src 'none'", "frame-src 'none'", "frame-ancestors 'none'",
  ].join('; ')
  return {
    ...config,
    basePath: BASE_PATH,
    distDir: '.next-design-preview',
    typescript: { ...config.typescript, tsconfigPath: 'preview/tsconfig.json' },
    // Client code prefixes API calls through lib/api.ts with this value.
    env: { ...config.env, PFT_CLIENT_BASE_PATH: BASE_PATH },
    async headers() {
      return [{ source: '/:path*', headers: [
        { key: 'Content-Security-Policy', value: policy },
        { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
        { key: 'Referrer-Policy', value: 'no-referrer' },
      ] }]
    },
    webpack(webpackConfig, options) {
      const resolved = config.webpack ? config.webpack(webpackConfig, options) : webpackConfig
      // react-plaid-link injects cdn.plaid.com on mount; the preview must make no Plaid calls.
      resolved.resolve.alias = { ...resolved.resolve.alias, 'react-plaid-link$': path.join(__dirname, 'plaid-link-stub.js') }
      return resolved
    },
  }
}
