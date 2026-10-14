import type { Metadata } from 'next'
import { Inter, Source_Serif_4 } from 'next/font/google'
import type { ReactNode } from 'react'

import { Providers } from '@/components/providers'

import './globals.css'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' })
const serif = Source_Serif_4({ subsets: ['latin'], variable: '--font-serif-display', display: 'swap', weight: ['400', '500', '600'] })

export const metadata: Metadata = {
  title: { default: 'Threadline', template: '%s · Threadline' },
  description: 'A local-first personal memory and intelligence workspace.',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${serif.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
