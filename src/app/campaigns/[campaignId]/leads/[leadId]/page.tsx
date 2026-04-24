'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useApiClient } from '@/hooks/useApiClient'
import { Badge, TagList, Spinner } from '@/components/ui'
import { cn, leadStatusColor, decisionColor, statusLabel, formatPercent, getInitials } from '@/lib/utils'
import type { LeadResponse } from '@/types/api'
import { toast } from 'sonner'
import {
  ArrowLeft, Mail, Phone, Linkedin, Building2,
  MapPin, Users, TrendingUp, Star,
} from 'lucide-react'

export default function LeadDetailPage() {
  const params        = useParams<{ campaignId: string; leadId: string }>()
  const { getClient } = useApiClient()

  const [lead, setLead]       = useState<LeadResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.getLead(params.campaignId, params.leadId)
      setLead(res)
    } catch {
      toast.error('Failed to load lead')
    } finally {
      setLoading(false)
    }
  }, [getClient, params.campaignId, params.leadId])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <div className="skeleton h-8 w-48 mb-6" />
        <div className="card skeleton h-64" />
      </div>
    )
  }

  if (!lead) return null

  const q = lead.qualification
  const e = lead.enrichment

  return (
    <div className="p-8 max-w-3xl mx-auto animate-fade-in">
      {/* Back */}
      <Link
        href={`/campaigns/${params.campaignId}`}
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-5 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Campaign
      </Link>

      {/* Header card */}
      <div className="card p-6 mb-4">
        <div className="flex items-start gap-4">
          {/* Avatar */}
          <div className="w-14 h-14 rounded-2xl bg-brand-100 flex items-center justify-center flex-shrink-0">
            <span className="text-lg font-semibold text-brand-700">{getInitials(lead.name)}</span>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold text-ink">{lead.name || '—'}</h1>
                <p className="text-sm text-ink-muted">{lead.title || '—'}</p>
              </div>
              <span className={cn('badge flex-shrink-0', leadStatusColor(lead.status))}>
                {statusLabel(lead.status)}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-muted">
              {lead.email && (
                <a href={`mailto:${lead.email}`} className="flex items-center gap-1.5 hover:text-brand-600 transition-colors">
                  <Mail size={12} /> {lead.email}
                </a>
              )}
              {lead.phone && (
                <a href={`tel:${lead.phone}`} className="flex items-center gap-1.5 hover:text-brand-600 transition-colors">
                  <Phone size={12} /> {lead.phone}
                </a>
              )}
              {lead.linkedin && (
                <a href={lead.linkedin} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 hover:text-brand-600 transition-colors">
                  <Linkedin size={12} /> LinkedIn
                </a>
              )}
              {lead.company && (
                <span className="flex items-center gap-1.5">
                  <Building2 size={12} /> {lead.company}
                  {lead.company_size && ` · ${lead.company_size.toLocaleString()} employees`}
                </span>
              )}
              {(lead.country || lead.location) && (
                <span className="flex items-center gap-1.5">
                  <MapPin size={12} /> {lead.country || lead.location}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Qualification */}
      {q && (
        <div className="card p-6 mb-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-ink flex items-center gap-2">
              <TrendingUp size={16} /> Qualification
            </h2>
            <span className={cn('badge', decisionColor(q.decision))}>
              {q.decision ? statusLabel(q.decision) : '—'}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs text-ink-subtle mb-1">ICP Match Score</p>
              <p className="text-2xl font-semibold text-ink">
                {q.icp_match_score != null ? `${Math.round(q.icp_match_score * 100)}%` : '—'}
              </p>
            </div>
            {q.recommended_angle && (
              <div>
                <p className="text-xs text-ink-subtle mb-1">Recommended Angle</p>
                <p className="text-sm text-ink">{q.recommended_angle}</p>
              </div>
            )}
          </div>

          {q.decision_reason && (
            <div className="mb-4 p-3 bg-surface-50 rounded-xl">
              <p className="text-xs text-ink-subtle mb-1">Decision Reason</p>
              <p className="text-sm text-ink leading-relaxed">{q.decision_reason}</p>
            </div>
          )}

          {q.blocking_issues && q.blocking_issues.length > 0 && (
            <div className="mb-3">
              <p className="text-xs text-ink-subtle mb-2">Blocking Issues</p>
              <div className="space-y-1">
                {q.blocking_issues.map((issue, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-red-600">
                    <span className="text-red-400 mt-0.5">✕</span> {issue}
                  </div>
                ))}
              </div>
            </div>
          )}

          {q.review_flags && q.review_flags.length > 0 && (
            <div>
              <p className="text-xs text-ink-subtle mb-2">Review Flags</p>
              <div className="flex flex-wrap gap-2">
                {q.review_flags.map((flag, i) => (
                  <span key={i} className="badge bg-amber-100 text-amber-700">{flag}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Enrichment */}
      {e && (
        <div className="card p-6 mb-4">
          <h2 className="font-semibold text-ink flex items-center gap-2 mb-4">
            <Star size={16} /> Enrichment
          </h2>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs text-ink-subtle mb-1">Identity Status</p>
              <p className="text-sm font-medium text-ink">{e.identity_status || '—'}</p>
            </div>
            <div>
              <p className="text-xs text-ink-subtle mb-1">Confidence Score</p>
              <p className="text-sm font-medium text-ink">{formatPercent(e.confidence_score)}</p>
            </div>
            {e.current_title && (
              <div className="col-span-2">
                <p className="text-xs text-ink-subtle mb-1">Current Title (Verified)</p>
                <p className="text-sm font-medium text-ink">{e.current_title}</p>
              </div>
            )}
          </div>

          {e.enrichment_summary && (
            <div className="mb-4 p-3 bg-surface-50 rounded-xl">
              <p className="text-xs text-ink-subtle mb-1">Summary</p>
              <p className="text-sm text-ink leading-relaxed">{e.enrichment_summary}</p>
            </div>
          )}

          {e.notable_achievements && e.notable_achievements.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-ink-subtle mb-2">Notable Achievements</p>
              <div className="space-y-1">
                {e.notable_achievements.map((a, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-ink">
                    <span className="text-brand-400 mt-0.5">→</span> {a}
                  </div>
                ))}
              </div>
            </div>
          )}

          {e.company_signals && e.company_signals.length > 0 && (
            <div>
              <p className="text-xs text-ink-subtle mb-2">Company Signals</p>
              <div className="flex flex-wrap gap-2">
                {e.company_signals.map((sig, i) => (
                  <span key={i} className="badge bg-surface-100 text-ink-muted border border-surface-200">
                    {Object.values(sig).join(': ')}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Raw details */}
      <div className="card p-6">
        <h2 className="font-semibold text-ink mb-4">Lead Details</h2>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
          {[
            ['Provider',     lead.provider || '—'],
            ['Lead Type',    lead.lead_type || '—'],
            ['Email Status', lead.email_status || '—'],
            ['Industry',     lead.industry || '—'],
            ['Seniority',    lead.seniority || '—'],
            ['Company Size', lead.company_size?.toLocaleString() || '—'],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-ink-subtle mb-0.5">{k}</dt>
              <dd className="font-medium text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* View emails CTA */}
      {lead.status === 'email_written' && (
        <Link
          href={`/campaigns/${params.campaignId}/emails/${params.leadId}`}
          className="mt-4 w-full btn-primary justify-center"
        >
          <Mail size={15} /> View Email Sequence
        </Link>
      )}
    </div>
  )
}
