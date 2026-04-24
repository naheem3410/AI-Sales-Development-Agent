import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

export function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${Math.round(value * 100)}%`
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toLocaleString()
}

export function statusLabel(status: string): string {
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function campaignStatusColor(status: string): string {
  switch (status) {
    case 'campaign_complete': return 'text-status-complete'
    case 'failed':
    case 'onboarding_failed': return 'text-status-failed'
    case 'cancelled':         return 'text-ink-subtle'
    case 'running':
    case 'onboarding':
    case 'ingesting':
    case 'enriching':
    case 'qualifying':
    case 'generating_emails': return 'text-status-running'
    default:                  return 'text-ink-muted'
  }
}

export function leadStatusColor(status: string): string {
  switch (status) {
    case 'qualified':     return 'bg-green-100 text-green-700'
    case 'email_written': return 'bg-blue-100 text-blue-700'
    case 'review':        return 'bg-amber-100 text-amber-700'
    case 'disqualified':  return 'bg-red-100 text-red-700'
    case 'enriched':      return 'bg-purple-100 text-purple-700'
    case 'queried':       return 'bg-indigo-100 text-indigo-700'
    case 'ingested':
    default:              return 'bg-surface-200 text-ink-muted'
  }
}

export function decisionColor(decision: string | null): string {
  switch (decision) {
    case 'approved':      return 'bg-green-100 text-green-700'
    case 'review':        return 'bg-amber-100 text-amber-700'
    case 'rejected':
    case 'disqualified':  return 'bg-red-100 text-red-700'
    default:              return 'bg-surface-200 text-ink-muted'
  }
}

export function truncate(str: string, len = 80): string {
  return str.length <= len ? str : str.slice(0, len) + '…'
}

export function getInitials(name: string | null | undefined): string {
  if (!name) return '?'
  return name
    .split(' ')
    .map((n) => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

export function companySize(min: number | null, max: number | null): string {
  if (!min && !max) return 'Any size'
  if (!min) return `Up to ${max}`
  if (!max) return `${min}+`
  return `${min}–${max}`
}

/** Human-readable message from API client errors (FastAPI `detail`). */
export function formatApiError(err: unknown): string {
  const e = err as Error & { detail?: unknown; status?: number }
  const raw = e.detail
  if (raw && typeof raw === 'object' && raw !== null && 'detail' in raw) {
    const d = (raw as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d) && d[0] && typeof (d[0] as { msg?: string }).msg === 'string') {
      return (d[0] as { msg: string }).msg
    }
  }
  if (typeof raw === 'string') return raw
  return e.message || 'Request failed'
}
