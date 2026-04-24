'use client'
import { cn } from '@/lib/utils'
import { Loader2 } from 'lucide-react'

// ── Spinner ───────────────────────────────────────────────────────────────────
export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={cn('animate-spin text-ink-subtle', className)} />
}

// ── Badge ─────────────────────────────────────────────────────────────────────
interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'brand'
  className?: string
}

const badgeVariants = {
  default: 'bg-surface-200 text-ink-muted',
  success: 'bg-green-100 text-green-700',
  warning: 'bg-amber-100 text-amber-700',
  danger:  'bg-red-100 text-red-700',
  info:    'bg-purple-100 text-purple-700',
  brand:   'bg-brand-100 text-brand-700',
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span className={cn('badge', badgeVariants[variant], className)}>
      {children}
    </span>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────
interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  accent?: string
  loading?: boolean
}

export function StatCard({ label, value, sub, accent, loading }: StatCardProps) {
  return (
    <div className="card p-5">
      <p className="text-xs font-medium text-ink-subtle uppercase tracking-wide mb-2">{label}</p>
      {loading ? (
        <div className="skeleton h-8 w-24 mb-1" />
      ) : (
        <p className={cn('text-2xl font-semibold', accent || 'text-ink')}>{value}</p>
      )}
      {sub && <p className="text-xs text-ink-subtle mt-0.5">{sub}</p>}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────
interface EmptyProps {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
}

export function Empty({ icon, title, description, action }: EmptyProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center px-6">
      {icon && (
        <div className="w-12 h-12 rounded-2xl bg-surface-100 flex items-center justify-center mb-4 text-ink-ghost">
          {icon}
        </div>
      )}
      <p className="font-medium text-ink mb-1">{title}</p>
      {description && <p className="text-sm text-ink-muted max-w-xs">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

// ── Page header ───────────────────────────────────────────────────────────────
interface PageHeaderProps {
  title: string
  description?: string
  action?: React.ReactNode
  back?: React.ReactNode
}

export function PageHeader({ title, description, action, back }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between mb-8">
      <div>
        {back && <div className="mb-3">{back}</div>}
        <h1 className="text-2xl font-semibold text-ink tracking-tight">{title}</h1>
        {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
      </div>
      {action && <div className="flex-shrink-0 ml-4">{action}</div>}
    </div>
  )
}

// ── Loading skeleton rows ─────────────────────────────────────────────────────
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-14 w-full" style={{ opacity: 1 - i * 0.15 }} />
      ))}
    </div>
  )
}

// ── Confirm dialog ────────────────────────────────────────────────────────────
interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
  danger?: boolean
}

export function ConfirmDialog({
  open, title, description, confirmLabel = 'Confirm',
  onConfirm, onCancel, loading, danger
}: ConfirmDialogProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink/30 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative card shadow-modal w-full max-w-sm p-6 animate-slide-up">
        <h3 className="font-semibold text-ink mb-2">{title}</h3>
        <p className="text-sm text-ink-muted mb-6">{description}</p>
        <div className="flex gap-3 justify-end">
          <button className="btn-secondary btn-sm" onClick={onCancel} disabled={loading}>
            Cancel
          </button>
          <button
            className={cn(danger ? 'btn-danger' : 'btn-primary', 'btn-sm')}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? <Spinner size={13} /> : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tag list (chip array) ─────────────────────────────────────────────────────
export function TagList({ items, emptyText = 'None' }: { items?: string[] | null; emptyText?: string }) {
  if (!items || items.length === 0) {
    return <span className="text-sm text-ink-ghost">{emptyText}</span>
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className="badge bg-surface-100 text-ink-muted border border-surface-200">
          {item}
        </span>
      ))}
    </div>
  )
}

// ── Progress bar ─────────────────────────────────────────────────────────────
export function ProgressBar({ value, max, color = 'bg-brand-500' }: {
  value: number; max: number; color?: string
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-1.5 bg-surface-200 rounded-full overflow-hidden">
      <div
        className={cn('h-full rounded-full transition-all duration-500', color)}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
