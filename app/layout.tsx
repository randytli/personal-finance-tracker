import type { Metadata, Viewport } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Personal Finance Tracker',
  description: 'A privacy-first web app that aggregates bank accounts via Plaid, de-duplicates & categorises transactions, and surfaces spending insights.',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#f6f7f9',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="pft-app min-h-screen bg-background">
          {children}
        </div>
      </body>
    </html>
  )
}
