'use client'
import { SignIn } from '@clerk/nextjs'
import { config } from '@/config'

export default function SignInPage() {
  return (
    <div className="min-h-screen bg-surface-50 flex">
      {/* Left panel - branding */}
      <div className="hidden lg:flex flex-col justify-between w-[480px] bg-brand-950 p-12 flex-shrink-0">
        <div>
          <div className="flex items-center gap-2.5 mb-16">
            <div className="w-8 h-8 bg-brand-400 rounded-lg flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 8L6 12L14 4" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <span className="text-white font-semibold text-lg">{config.app.name}</span>
          </div>

          <h1 className="font-display text-4xl text-white leading-tight mb-4">
            Your AI sales team,<br />
            <em>ready to run.</em>
          </h1>
          <p className="text-brand-300 text-base leading-relaxed">
            Research, qualify, and reach prospects with AI that works overnight — so your team closes, not cold-calls.
          </p>
        </div>

        <div className="space-y-4">
          {[
            ['Automated ICP generation', 'Scrapes your website to build a precise ideal customer profile.'],
            ['Multi-source enrichment', 'Gathers evidence across the web per lead before scoring.'],
            ['3-email sequences', 'Personalised outbound copy, ready to send.'],
          ].map(([title, desc]) => (
            <div key={title} className="flex gap-3">
              <div className="w-5 h-5 rounded-full bg-brand-700 flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <path d="M1.5 5L4 7.5L8.5 2.5" stroke="#7287fd" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div>
                <p className="text-white text-sm font-medium">{title}</p>
                <p className="text-brand-400 text-xs leading-relaxed">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel - Clerk sign-in */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="lg:hidden mb-8 flex items-center gap-2.5">
            <div className="w-8 h-8 bg-brand-600 rounded-lg flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 8L6 12L14 4" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <span className="font-semibold text-lg text-ink">{config.app.name}</span>
          </div>
          <SignIn
            appearance={{
              elements: {
                rootBox: 'w-full',
                card: 'shadow-none bg-transparent p-6 sm:p-8',
                headerTitle: 'text-xl font-semibold text-ink',
                headerSubtitle: 'text-ink-muted',
                formButtonPrimary: 'btn-primary w-full',
                formFieldInput: 'input',
                formFieldLabel: 'label',
                footerActionLink: 'text-brand-600 hover:text-brand-700',
              },
            }}
          />
        </div>
      </div>
    </div>
  )
}
