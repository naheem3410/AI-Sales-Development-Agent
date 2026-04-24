'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useApiClient } from '@/hooks/useApiClient'
import { Spinner } from '@/components/ui'
import { cn, formatApiError, getInitials, formatDateTime } from '@/lib/utils'
import type { EmailSequenceResponse, UpdateEmailRequest, UserResponse } from '@/types/api'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Edit2,
  Save,
  X,
  CheckCircle,
  Send,
  AlertCircle,
} from 'lucide-react'

export default function EmailSequencePage() {
  const params        = useParams<{ campaignId: string; leadId: string }>()
  const { getClient } = useApiClient()

  const [seq, setSeq]           = useState<EmailSequenceResponse | null>(null)
  const [loading, setLoading]   = useState(true)
  const [editing, setEditing]   = useState<1 | 2 | 3 | null>(null)
  const [saving, setSaving]     = useState(false)
  const [draft, setDraft]       = useState<UpdateEmailRequest>({})

  const [user, setUser]               = useState<UserResponse | null>(null)
  const [outreachReady, setOutreachReady] = useState(false)
  const [sendingFirst, setSendingFirst] = useState(false)

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const [res, me, outreach] = await Promise.all([
        client.getEmailSequence(params.campaignId, params.leadId),
        client.getMe().catch(() => null),
        client.getOutreachSettings().catch(() => null),
      ])
      setSeq(res)
      setUser(me)
      setOutreachReady(Boolean(outreach?.is_configured && outreach?.has_api_key))
    } catch {
      toast.error('Failed to load email sequence')
    } finally {
      setLoading(false)
    }
  }, [getClient, params.campaignId, params.leadId])

  useEffect(() => { load() }, [load])

  const startEdit = (n: 1 | 2 | 3) => {
    if (!seq) return
    setDraft({
      [`email_${n}_subject`]: seq[`email_${n}`].subject ?? '',
      [`email_${n}_body`]:    seq[`email_${n}`].body    ?? '',
    })
    setEditing(n)
  }

  const cancelEdit = () => { setEditing(null); setDraft({}) }

  const save = async () => {
    setSaving(true)
    try {
      const client = await getClient()
      const res = await client.updateEmailSequence(params.campaignId, params.leadId, draft)
      setSeq(res)
      setEditing(null)
      setDraft({})
      toast.success('Email updated')
    } catch {
      toast.error('Failed to save email')
    } finally {
      setSaving(false)
    }
  }

  const sendFirstEmail = async () => {
    if (!user?.has_active_subscription) {
      toast.error('An active subscription is required to send outreach.')
      return
    }
    setSendingFirst(true)
    try {
      const client = await getClient()
      await client.sendOutreachEmail(params.campaignId, params.leadId, { email_number: 1 })
      toast.success('Email 1 is sending — this can take a few seconds.')
      await load()
    } catch (e) {
      toast.error(formatApiError(e))
    } finally {
      setSendingFirst(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <div className="skeleton h-8 w-48 mb-6" />
        <div className="space-y-4">
          {[1,2,3].map(i => <div key={i} className="skeleton h-40" />)}
        </div>
      </div>
    )
  }

  if (!seq) return null

  const emails: { n: 1 | 2 | 3; label: string }[] = [
    { n: 1, label: 'Email 1 — Opening' },
    { n: 2, label: 'Email 2 — Follow-up' },
    { n: 3, label: 'Email 3 — Break-up' },
  ]

  return (
    <div className="p-8 max-w-2xl mx-auto animate-fade-in">
      {/* Back */}
      <Link
        href={`/campaigns/${params.campaignId}`}
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-5 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Campaign
      </Link>

      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 rounded-2xl bg-brand-100 flex items-center justify-center flex-shrink-0">
          <span className="text-base font-semibold text-brand-700">{getInitials(seq.lead_name)}</span>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-ink">{seq.lead_name || seq.lead_email}</h1>
          <p className="text-sm text-ink-muted">{seq.lead_email}</p>
        </div>
      </div>

      {/* Sequence notes */}
      {seq.sequence_notes && (
        <div className="mb-6 p-4 bg-brand-50 border border-brand-200 rounded-xl">
          <p className="text-xs text-brand-600 font-medium mb-1">Sequence Notes</p>
          <p className="text-sm text-brand-800">{seq.sequence_notes}</p>
        </div>
      )}

      {/* Send first email — matches pipeline + outreach flow */}
      {!seq.email_1_sent_at && (
        <div className="mb-8 card overflow-hidden border-2 border-brand-200 shadow-card-hover">
          <div className="px-5 py-4 border-b border-surface-200 bg-gradient-to-r from-brand-50 to-white flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex gap-3">
              <div className="w-10 h-10 rounded-xl bg-brand-600 flex items-center justify-center flex-shrink-0">
                <Send size={18} className="text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-ink">Ready to send Email 1?</p>
                <p className="text-xs text-ink-muted mt-1 max-w-xl">
                  When the copy looks right, send the opening email to{' '}
                  <span className="font-medium text-ink">{seq.lead_email}</span>. Follow-ups are scheduled
                  automatically after a successful send.
                </p>
              </div>
            </div>
            <div className="flex flex-col sm:items-end gap-2">
              {!user?.has_active_subscription && (
                <p className="text-xs text-amber-700 flex items-center gap-1.5 flex-wrap">
                  <AlertCircle size={13} /> Active subscription required to send —{' '}
                  <Link href="/billing" className="underline font-medium hover:text-amber-900">
                    subscribe
                  </Link>
                  .
                </p>
              )}
              {!outreachReady && (
                <p className="text-xs text-ink-muted">
                  Configure{' '}
                  <Link href="/settings/outreach" className="text-brand-600 hover:text-brand-700 font-medium">
                    Resend &amp; sending identity
                  </Link>{' '}
                  first.
                </p>
              )}
              <button
                type="button"
                className="btn-primary w-full sm:w-auto min-w-[160px]"
                onClick={sendFirstEmail}
                disabled={
                  sendingFirst || !user?.has_active_subscription || !outreachReady
                }
              >
                {sendingFirst ? <Spinner size={15} /> : <Send size={15} />}
                Send first email
              </button>
              <Link
                href="/knowledge"
                className="text-xs text-brand-600 hover:text-brand-700 text-center sm:text-right"
              >
                Optional: add FAQs to Knowledge for smarter replies →
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Emails */}
      <div className="space-y-4">
        {emails.map(({ n, label }) => {
          const email   = seq[`email_${n}`]
          const sentAt  = seq[`email_${n}_sent_at`]
          const isEditing = editing === n

          return (
            <div key={n} className={cn('card overflow-hidden', isEditing && 'ring-2 ring-brand-400')}>
              {/* Email header */}
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-surface-200 bg-surface-50">
                <div className="flex items-center gap-2.5">
                  <div className="w-6 h-6 rounded-full bg-brand-600 flex items-center justify-center">
                    <span className="text-xs font-bold text-white">{n}</span>
                  </div>
                  <span className="text-sm font-medium text-ink">{label}</span>
                  {sentAt && (
                    <span className="flex items-center gap-1 text-xs text-green-600">
                      <CheckCircle size={11} /> Sent {formatDateTime(sentAt)}
                    </span>
                  )}
                </div>

                {!isEditing ? (
                  <button className="btn-ghost btn-sm" onClick={() => startEdit(n)}>
                    <Edit2 size={13} /> Edit
                  </button>
                ) : (
                  <div className="flex gap-2">
                    <button className="btn-ghost btn-sm" onClick={cancelEdit} disabled={saving}>
                      <X size={13} /> Cancel
                    </button>
                    <button className="btn-primary btn-sm" onClick={save} disabled={saving}>
                      {saving ? <Spinner size={13} /> : <Save size={13} />} Save
                    </button>
                  </div>
                )}
              </div>

              <div className="p-5">
                {isEditing ? (
                  <div className="space-y-3">
                    <div>
                      <label className="label">Subject</label>
                      <input
                        className="input"
                        value={(draft[`email_${n}_subject` as keyof UpdateEmailRequest] as string) ?? ''}
                        onChange={(e) => setDraft((p) => ({ ...p, [`email_${n}_subject`]: e.target.value }))}
                      />
                    </div>
                    <div>
                      <label className="label">Body</label>
                      <textarea
                        className="input min-h-[240px] resize-y font-mono text-xs"
                        value={(draft[`email_${n}_body` as keyof UpdateEmailRequest] as string) ?? ''}
                        onChange={(e) => setDraft((p) => ({ ...p, [`email_${n}_body`]: e.target.value }))}
                      />
                    </div>
                  </div>
                ) : (
                  <div>
                    <p className="text-xs text-ink-subtle mb-1">Subject</p>
                    <p className="text-sm font-medium text-ink mb-4">
                      {email.subject || <span className="text-ink-ghost">No subject</span>}
                    </p>
                    <p className="text-xs text-ink-subtle mb-2">Body</p>
                    <div className="text-sm text-ink whitespace-pre-wrap leading-relaxed bg-surface-50 rounded-xl p-4 font-mono text-xs">
                      {email.body || <span className="text-ink-ghost">No content</span>}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
