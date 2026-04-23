'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Empty, SkeletonRows } from '@/components/ui'
import { getInitials, truncate } from '@/lib/utils'
import type { EmailSequenceResponse } from '@/types/api'
import { toast } from 'sonner'
import { Mail, ArrowRight } from 'lucide-react'

interface Props { campaignId: string }

export default function EmailsTab({ campaignId }: Props) {
  const { getClient }   = useApiClient()
  const [sequences, setSequences] = useState<EmailSequenceResponse[]>([])
  const [loading, setLoading]     = useState(true)

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.listEmails(campaignId)
      setSequences(res.sequences)
    } catch {
      toast.error('Failed to load emails')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-4"><SkeletonRows rows={6} /></div>
        ) : sequences.length === 0 ? (
          <Empty
            icon={<Mail size={22} />}
            title="No emails generated yet"
            description="Email sequences will appear here once the pipeline completes for approved and review leads."
          />
        ) : (
          <div className="divide-y divide-surface-100">
            {sequences.map((seq) => (
              <Link
                key={seq.id}
                href={`/campaigns/${campaignId}/emails/${seq.lead_id}`}
                className="flex items-center gap-4 px-5 py-4 hover:bg-surface-50 transition-colors group"
              >
                {/* Avatar */}
                <div className="w-9 h-9 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-semibold text-brand-700">
                    {getInitials(seq.lead_name)}
                  </span>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink truncate group-hover:text-brand-700 transition-colors">
                    {seq.lead_name || seq.lead_email}
                  </p>
                  <p className="text-xs text-ink-subtle truncate">{seq.lead_email}</p>
                </div>

                {/* Email 1 preview */}
                <div className="hidden md:block flex-1 min-w-0">
                  <p className="text-xs font-medium text-ink truncate">
                    {seq.email_1.subject || 'No subject'}
                  </p>
                  <p className="text-xs text-ink-subtle truncate">
                    {truncate(seq.email_1.body?.replace(/\n/g, ' ') || '', 60)}
                  </p>
                </div>

                {/* Sent indicators */}
                <div className="hidden sm:flex items-center gap-1.5 flex-shrink-0">
                  {[seq.email_1_sent_at, seq.email_2_sent_at, seq.email_3_sent_at].map((sent, i) => (
                    <div
                      key={i}
                      title={sent ? `Email ${i + 1} sent` : `Email ${i + 1} not sent`}
                      className={`w-2 h-2 rounded-full ${sent ? 'bg-brand-500' : 'bg-surface-300'}`}
                    />
                  ))}
                </div>

                <ArrowRight size={14} className="text-ink-ghost group-hover:text-brand-600 transition-colors flex-shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
