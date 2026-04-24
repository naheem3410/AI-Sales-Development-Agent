// ─── SDA Platform — frontend app config (client + server) ─────────────────────
// Next.js inlines `NEXT_PUBLIC_*` at build time. Copy `.env.local.example` → `.env.local`.

import type { Provider } from '@/types/api'

function envStr(key: string, fallback: string): string {
  if (typeof process === 'undefined') return fallback
  const v = process.env[key]
  return v !== undefined && v !== '' ? v : fallback
}

function envInt(key: string, fallback: number): number {
  if (typeof process === 'undefined') return fallback
  const v = process.env[key]
  if (v === undefined || v === '') return fallback
  const n = parseInt(v, 10)
  return Number.isFinite(n) ? n : fallback
}

const defaultProvider: Provider = (() => {
  const raw = envStr('NEXT_PUBLIC_DEFAULT_CAMPAIGN_PROVIDER', 'prospeo')
  return raw === 'apollo' || raw === 'prospeo' ? raw : 'prospeo'
})()

export const config = {
  app: {
    name: envStr('NEXT_PUBLIC_APP_NAME', 'SDA Platform'),
    tagline: envStr('NEXT_PUBLIC_APP_TAGLINE', 'AI-powered outbound'),
  },
  clerk: {
    publishableKey: envStr('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', ''),
    signInUrl: envStr('NEXT_PUBLIC_CLERK_SIGN_IN_URL', '/sign-in'),
    signUpUrl: envStr('NEXT_PUBLIC_CLERK_SIGN_UP_URL', '/sign-up'),
  },
  api: {
    baseUrl: envStr('NEXT_PUBLIC_API_BASE_URL', ''),
  },
  polling: {
    pipelineInterval: envInt('NEXT_PUBLIC_PIPELINE_POLL_INTERVAL', 5000),
    onboardingInterval: envInt('NEXT_PUBLIC_ONBOARDING_POLL_INTERVAL', 3000),
    maxRetries: envInt('NEXT_PUBLIC_POLLING_MAX_RETRIES', 8),
  },
  billing: {
    monthlyPriceUsd: envInt('NEXT_PUBLIC_BILLING_MONTHLY_USD', 29),
    planDisplayName: envStr('NEXT_PUBLIC_BILLING_PLAN_NAME', 'Pro'),
    path: envStr('NEXT_PUBLIC_BILLING_PATH', '/billing'),
  },
  campaign: {
    defaultProvider,
  },
  leads: {
    defaultTargetCount: envInt('NEXT_PUBLIC_LEADS_DEFAULT_TARGET', 25),
    pageSize: envInt('NEXT_PUBLIC_LEADS_PAGE_SIZE', 25),
  },
} as const
