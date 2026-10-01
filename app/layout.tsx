import type { Metadata, Viewport } from 'next'
import { Public_Sans, Source_Serif_4 } from 'next/font/google'
import './globals.css'

const sans = Public_Sans({ subsets: ['latin'], variable: '--font-sans' })
const serif = Source_Serif_4({ subsets: ['latin'], axes: ['opsz'], variable: '--font-serif' })

export const metadata: Metadata = {
  title: 'Personal Finance Tracker',
  description: 'A privacy-first web app that aggregates bank accounts via Plaid, de-duplicates & categorises transactions, and surfaces spending insights.',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#f1f3ee',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${serif.variable}`}>
        <div className="pft-app min-h-screen bg-background">
          {children}
        </div>
      </body>
    </html>
  )
}
