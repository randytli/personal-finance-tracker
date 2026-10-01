// Design-preview replacement for react-plaid-link: never loads Plaid's script or opens Link.
export function usePlaidLink() {
  return { open() {}, exit() {}, submit() {}, ready: false, error: null }
}
