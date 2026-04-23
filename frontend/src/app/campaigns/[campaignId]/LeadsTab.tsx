'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Empty, SkeletonRows } from '@/components/ui'
import { cn, leadStatusColor, statusLabel, getInitials } from '@/lib/utils'
import { config } from '@/config'
import type { LeadPipelineFilter, LeadResponse } from '@/types/api'
import { toast } from 'sonner'
import {
  Users,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
  Building2,
  MapPin,
  Check,
  X,
} from 'lucide-react'

const STATUS_FILTERS: { value: LeadPipelineFilter | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'email_written', label: 'Email Written' },
  { value: 'qualified', label: 'Approved' },
  { value: 'review', label: 'Review' },
  { value: 'disqualified', label: 'Rejected' },
  { value: 'enriched', label: 'Enriched' },
  { value: 'ingested', label: 'Ingested' },
  { value: 'converted', label: 'Converted' },
]

interface Props {
  campaignId: string
  /** Refetch campaign entity (updates header summary counts after review actions). */
  onCampaignMutated?: () => void | Promise<void>
}

export default function LeadsTab({ campaignId, onCampaignMutated }: Props) {
  const { getClient } = useApiClient()
  const PAGE_SIZE = config.leads.pageSize

  const [leads, setLeads] = useState<LeadResponse[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatus] = useState<LeadPipelineFilter | 'all'>('all')
  const [page, setPage] = useState(1)
  const [busyLeadId, setBusyLeadId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const client = await getClient()
      const res = await client.listLeads(
        campaignId,
        statusFilter === 'all' ? undefined : statusFilter
      )
      setLeads(res.leads)
      setTotal(res.total)
      setPage(1)
    } catch {
      toast.error('Failed to load leads')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const resolveReview = async (leadId: string, resolution: 'approve' | 'reject') => {
    setBusyLeadId(leadId)
    try {
      const client = await getClient()
      await client.resolveLeadReview(campaignId, leadId, resolution)
      toast.success(resolution === 'approve' ? 'Lead approved' : 'Lead rejected')
      await load()
      await onCampaignMutated?.()
    } catch {
      toast.error('Could not update lead — it may already be resolved.')
    } finally {
      setBusyLeadId(null)
    }
  }

  const totalPages = Math.max(1, Math.ceil(leads.length / PAGE_SIZE))
  const pageLeads = leads.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const showReviewActions = statusFilter === 'review'

  return (
    <div>
      {/* Filter bar */}
      <div className="flex items-center gap-1.5 mb-4 flex-wrap">
        {STATUS_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => {
              setStatus(value as LeadPipelineFilter | 'all')
            }}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-medium transition-all border',
              statusFilter === value
                ? 'bg-brand-600 text-white border-brand-600'
                : 'bg-white text-ink-muted border-surface-300 hover:border-brand-400 hover:text-ink'
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-ink-subtle">{total} total</span>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : pageLeads.length === 0 ? (
          <Empty
            icon={<Users size={22} />}
            title="No leads found"
            description={
              statusFilter !== 'all'
                ? 'Try a different filter.'
                : 'Leads will appear here once the pipeline runs.'
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-200">
                    {['Lead', 'Company', 'Title', 'Location', 'Status', ...(showReviewActions ? ['Actions'] : []), ''].map((h) => (
                      <th
                        key={h}
                        className="text-left px-4 py-3 text-xs font-medium text-ink-subtle uppercase tracking-wide whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-100">
                  {pageLeads.map((lead) => (
                    <tr key={lead.id} className="hover:bg-surface-50 transition-colors group">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0">
                            <span className="text-xs font-semibold text-brand-700">
                              {getInitials(lead.name)}
                            </span>
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium text-ink truncate max-w-[160px]">{lead.name || '—'}</p>
                            <p className="text-xs text-ink-subtle truncate max-w-[160px]">{lead.email || '—'}</p>
                          </div>
                        </div>
                      </td>

                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 text-ink-muted">
                          <Building2 size={12} />
                          <span className="truncate max-w-[140px]">{lead.company || '—'}</span>
                        </div>
                      </td>

                      <td className="px-4 py-3 text-ink-muted truncate max-w-[160px]">{lead.title || '—'}</td>

                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1 text-ink-muted">
                          <MapPin size={11} />
                          <span className="text-xs truncate max-w-[120px]">
                            {lead.country || lead.location || '—'}
                          </span>
                        </div>
                      </td>

                      <td className="px-4 py-3">
                        <span className={cn('badge', leadStatusColor(lead.status))}>
                          {statusLabel(lead.status)}
                        </span>
                      </td>

                      {showReviewActions && (
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              disabled={busyLeadId === lead.id}
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                void resolveReview(lead.id, 'approve')
                              }}
                              className="inline-flex items-center gap-0.5 px-2 py-1 rounded-lg text-xs font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                              title="Approve"
                            >
                              <Check size={12} />
                              Approve
                            </button>
                            <button
                              type="button"
                              disabled={busyLeadId === lead.id}
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                void resolveReview(lead.id, 'reject')
                              }}
                              className="inline-flex items-center gap-0.5 px-2 py-1 rounded-lg text-xs font-medium bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                              title="Reject"
                            >
                              <X size={12} />
                              Reject
                            </button>
                          </div>
                        </td>
                      )}

                      <td className="px-4 py-3 w-10">
                        <Link
                          href={`/campaigns/${campaignId}/leads/${lead.id}`}
                          className="opacity-0 group-hover:opacity-100 transition-opacity text-ink-ghost hover:text-brand-600"
                        >
                          <ArrowRight size={14} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-surface-200">
                <p className="text-xs text-ink-subtle">
                  Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, leads.length)} of{' '}
                  {leads.length}
                </p>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span className="text-xs text-ink-muted px-2">
                    {page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
