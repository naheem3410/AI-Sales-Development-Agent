'use client'
import { SignUp } from '@clerk/nextjs'
import { config } from '@/config'

export default function SignUpPage() {
  return (
    <div className="min-h-screen bg-surface-50 flex items-center justify-center p-8">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5">
          <div className="w-8 h-8 bg-brand-600 rounded-lg flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 8L6 12L14 4" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="font-semibold text-lg text-ink">{config.app.name}</span>
        </div>
        <SignUp
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
  )
}
