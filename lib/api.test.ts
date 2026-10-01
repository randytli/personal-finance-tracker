import fs from 'node:fs'
import path from 'node:path'

afterEach(() => { delete process.env.PFT_CLIENT_BASE_PATH; jest.resetModules() })

test('API paths are unchanged without a preview base path', () => {
  const { apiPath } = require('./api') as typeof import('./api')
  expect(apiPath('/api/pft/sync/status')).toBe('/api/pft/sync/status')
})

test('the design-preview base path prefixes API paths', () => {
  process.env.PFT_CLIENT_BASE_PATH = '/design-preview'
  const { apiPath } = require('./api') as typeof import('./api')
  expect(apiPath('/api/pft/review/categories')).toBe('/design-preview/api/pft/review/categories')
})

test('client source calls the API only through apiFetch', () => {
  const root = path.join(__dirname, '..')
  const sources = ['app', 'components'].flatMap(dir => (fs.readdirSync(path.join(root, dir), { recursive: true }) as string[])
    .filter(file => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file)).map(file => path.join(dir, file)))
  expect(sources.length).toBeGreaterThan(10)
  expect(sources.filter(file => /(?<![\w.])fetch\(/.test(fs.readFileSync(path.join(root, file), 'utf8')))).toEqual([])
})
