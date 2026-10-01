// Client API calls use absolute /api/pft paths, which Next.js basePath does not prefix.
// PFT_CLIENT_BASE_PATH is only defined by the design-preview build, so Production paths are unchanged.
const basePath = process.env.PFT_CLIENT_BASE_PATH || ''

export function apiPath(path: string) {
  return basePath + path
}

export function apiFetch(path: string, init?: RequestInit) {
  return fetch(apiPath(path), init)
}
