export const metadata = { title: 'PFT M5 auth probe', robots: { index: false, follow: false } }

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: 24, maxWidth: 760 }}>{children}</body>
    </html>
  )
}
