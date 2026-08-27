import PlaidLinkButton from '@/components/plaid-link-button'

export default function PlaidOAuthPage() {
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-semibold">Returning to Plaid Link</h1>
      <p className="my-4 text-muted-foreground">
        Keep this page open while the institution connection finishes.
      </p>
      <PlaidLinkButton resumeOAuth />
    </main>
  )
}
