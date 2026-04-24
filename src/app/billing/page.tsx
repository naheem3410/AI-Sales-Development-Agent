'use client'

import Link from 'next/link'
import { PricingTable } from '@clerk/nextjs'
import { ArrowLeft } from 'lucide-react'
import { config } from '@/config'

export default function BillingPage() {
  const { monthlyPriceUsd, planDisplayName } = config.billing

  return (
    <div className="p-8 max-w-3xl mx-auto animate-fade-in">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-6 transition-colors"
      >
        <ArrowLeft size={14} /> Back to dashboard
      </Link>

      <h1 className="text-2xl font-semibold text-ink tracking-tight mb-1">Subscribe</h1>
      <p className="text-sm text-ink-muted mb-2 max-w-xl">
        One paid plan — <span className="font-medium text-ink">{planDisplayName}</span> at{' '}
        <span className="font-medium text-ink">${monthlyPriceUsd} USD</span> per month (shown for your
        reference; the amount charged follows your Clerk plan settings).
      </p>
      <p className="text-xs text-ink-subtle mb-8">
        Use Stripe test cards in development (e.g. success card from Stripe&apos;s testing docs) when your
        Clerk instance uses the development gateway or Stripe test mode.
      </p>

      <div className="rounded-2xl border border-surface-200 bg-white p-6 shadow-card">
        <PricingTable
          for="user"
          ctaPosition="bottom"
          newSubscriptionRedirectUrl="/dashboard"
        />
      </div>

      <p className="text-[11px] text-ink-subtle mt-6">
        After checkout, you&apos;ll return to the dashboard — your backend unlocks pipelines when Clerk
        reports an active subscription.
      </p>
    </div>
  )
}
