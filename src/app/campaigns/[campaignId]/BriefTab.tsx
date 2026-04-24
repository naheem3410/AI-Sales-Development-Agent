'use client'
import { useState, useEffect, useCallback } from 'react'
import { useApiClient } from '@/hooks/useApiClient'
import { Spinner, Empty, TagList } from '@/components/ui'
import type { BriefResponse, UpdateBriefRequest } from '@/types/api'
import { toast } from 'sonner'
import { Edit2, Save, X, FileText } from 'lucide-react'

interface Props { campaignId: string }

export default function BriefTab({ campaignId }: Props) {
  const { getClient } = useApiClient()

  const [brief, setBrief]     = useState<BriefResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [draft, setDraft]     = useState<UpdateBriefRequest>({})

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.getBrief(campaignId)
      setBrief(res)
    } catch (err: unknown) {
      const status = (err as { status?: number }).status
      if (status !== 404) toast.error('Failed to load brief')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId])

  useEffect(() => { load() }, [load])

  const startEdit = () => {
    if (!brief) return
    setDraft({
      product_name:               brief.product_name,
      what_it_does:               brief.what_it_does,
      who_it_is_for:              brief.who_it_is_for,
      pain_it_solves:             brief.pain_it_solves,
      key_differentiators:        brief.key_differentiators,
      ideal_customer_description: brief.ideal_customer_description,
    })
    setEditing(true)
  }

  const cancelEdit = () => { setEditing(false); setDraft({}) }

  const save = async () => {
    setSaving(true)
    try {
      const client = await getClient()
      const res = await client.updateBrief(campaignId, draft)
      setBrief(res)
      setEditing(false)
      toast.success('Brief updated')
    } catch {
      toast.error('Failed to save brief')
    } finally {
      setSaving(false)
    }
  }

  const set = <K extends keyof UpdateBriefRequest>(k: K, v: UpdateBriefRequest[K]) =>
    setDraft((p) => ({ ...p, [k]: v }))

  if (loading) {
    return <div className="space-y-3">{[1,2,3].map(i => <div key={i} className="skeleton h-20" />)}</div>
  }

  if (!brief) {
    return (
      <div className="card">
        <Empty
          icon={<FileText size={22} />}
          title="Brief not generated yet"
          description="The onboarding agent will generate your product brief once it finishes analyzing your website."
        />
      </div>
    )
  }

  return (
    <div className="card p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h3 className="font-semibold text-ink mb-0.5">Product Brief</h3>
          <p className="text-xs text-ink-muted">
            Used by the email agent to write personalised outbound copy.
          </p>
        </div>
        {!editing ? (
          <button className="btn-secondary btn-sm" onClick={startEdit}>
            <Edit2 size={13} /> Edit Brief
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

      {editing ? (
        <div className="space-y-5">
          <div>
            <label className="label">Product Name</label>
            <input className="input" value={draft.product_name ?? ''} onChange={(e) => set('product_name', e.target.value)} />
          </div>
          <div>
            <label className="label">What It Does</label>
            <textarea className="input min-h-[100px] resize-y" value={draft.what_it_does ?? ''} onChange={(e) => set('what_it_does', e.target.value)} />
          </div>
          <div>
            <label className="label">Who It's For</label>
            <textarea className="input min-h-[80px] resize-y" value={draft.who_it_is_for ?? ''} onChange={(e) => set('who_it_is_for', e.target.value)} />
          </div>
          <div>
            <label className="label">Pain It Solves</label>
            <textarea className="input min-h-[80px] resize-y" value={draft.pain_it_solves ?? ''} onChange={(e) => set('pain_it_solves', e.target.value)} />
          </div>
          <div>
            <label className="label">Key Differentiators <span className="text-ink-ghost normal-case">(one per line)</span></label>
            <textarea
              className="input min-h-[100px] resize-y"
              value={(draft.key_differentiators ?? []).join('\n')}
              onChange={(e) => set('key_differentiators', e.target.value.split('\n').map(s => s.trim()).filter(Boolean))}
            />
          </div>
          <div>
            <label className="label">Ideal Customer Description</label>
            <textarea className="input min-h-[80px] resize-y" value={draft.ideal_customer_description ?? ''} onChange={(e) => set('ideal_customer_description', e.target.value)} />
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <div>
            <p className="text-xs text-ink-subtle mb-1">Product Name</p>
            <p className="text-lg font-semibold text-ink">{brief.product_name}</p>
          </div>

          {[
            { label: 'What It Does',     value: brief.what_it_does },
            { label: "Who It's For",     value: brief.who_it_is_for },
            { label: 'Pain It Solves',   value: brief.pain_it_solves },
            { label: 'Ideal Customer',   value: brief.ideal_customer_description },
          ].map(({ label, value }) => (
            <div key={label}>
              <p className="text-xs text-ink-subtle mb-1">{label}</p>
              <p className="text-sm text-ink leading-relaxed">{value}</p>
            </div>
          ))}

          <div>
            <p className="text-xs text-ink-subtle mb-2">Key Differentiators</p>
            <div className="space-y-2">
              {brief.key_differentiators.map((d, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <div className="w-5 h-5 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <span className="text-[10px] font-semibold text-brand-700">{i + 1}</span>
                  </div>
                  <p className="text-sm text-ink leading-relaxed">{d}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
