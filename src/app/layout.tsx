import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { Toaster } from 'sonner'
import { config } from '@/config'
import './globals.css'

export const metadata: Metadata = {
  title: `${config.app.name} — ${config.app.tagline}`,
  description: 'AI-powered outbound sales pipeline. Research prospects, qualify leads, write personalised emails — automatically.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider
      publishableKey={config.clerk.publishableKey}
      signInUrl={config.clerk.signInUrl}
      signUpUrl={config.clerk.signUpUrl}
    >
      <html lang="en" suppressHydrationWarning>
        <head>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
          <link
            href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..600&family=DM+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&display=swap"
            rel="stylesheet"
          />
        </head>
        <body className="antialiased bg-surface-50 text-ink">
          {children}
          <Toaster position="bottom-right" richColors />
        </body>
      </html>
    </ClerkProvider>
  )
}
