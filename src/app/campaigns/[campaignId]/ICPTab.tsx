'use client'
import { useState, useEffect, useCallback } from 'react'
import { useApiClient } from '@/hooks/useApiClient'
import { TagList, Spinner, Empty } from '@/components/ui'
import { cn, companySize, formatPercent } from '@/lib/utils'
import type { ICPResponse, UpdateICPRequest, Seniority } from '@/types/api'
import { toast } from 'sonner'
import { Edit2, Save, X, Target, AlertCircle } from 'lucide-react'

const SENIORITY_OPTIONS: Seniority[] = [
  'owner','founder','c_suite','partner','vp','head','director','manager','senior','entry','intern'
]

interface Props { campaignId: string }

export default function ICPTab({ campaignId }: Props) {
  const { getClient } = useApiClient()

  const [icp, setIcp]         = useState<ICPResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [draft, setDraft]     = useState<UpdateICPRequest>({})

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.getICP(campaignId)
      setIcp(res)
    } catch (err: unknown) {
      const status = (err as { status?: number }).status
      if (status !== 404) toast.error('Failed to load ICP')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId])

  useEffect(() => { load() }, [load])

  const startEdit = () => {
    if (!icp) return
    setDraft({
      target_type:       icp.target_type as UpdateICPRequest['target_type'],
      industry:          icp.industry,
      company_size_min:  icp.company_size_min ?? undefined,
      company_size_max:  icp.company_size_max ?? undefined,
      funding_status:    icp.funding_status ?? [],
      job_titles:        icp.job_titles,
      seniority:         (icp.seniority ?? []) as Seniority[],
      locations:         icp.locations,
      tech_stack:        icp.tech_stack ?? [],
      demographics:      icp.demographics ?? '',
    })
    setEditing(true)
  }

  const cancelEdit = () => { setEditing(false); setDraft({}) }

  const save = async () => {
    setSaving(true)
    try {
      const client = await getClient()
      const res = await client.updateICP(campaignId, draft)
      setIcp(res)
      setEditing(false)
      setDraft({})
      toast.success('ICP updated')
    } catch {
      toast.error('Failed to save ICP')
    } finally {
      setSaving(false)
    }
  }

  // ── Edit helpers ─────────────────────────────────────────────────────────
  const setField = <K extends keyof UpdateICPRequest>(k: K, v: UpdateICPRequest[K]) =>
    setDraft((p) => ({ ...p, [k]: v }))

  const toggleSeniority = (s: Seniority) => {
    const cur = (draft.seniority ?? []) as Seniority[]
    setField('seniority', cur.includes(s) ? cur.filter(x => x !== s) : [...cur, s])
  }

  const parseList = (val: string): string[] =>
    val.split(',').map(s => s.trim()).filter(Boolean)

  if (loading) {
    return <div className="space-y-3">{[1,2,3].map(i => <div key={i} className="skeleton h-16" />)}</div>
  }

  if (!icp) {
    return (
      <div className="card">
        <Empty
          icon={<Target size={22} />}
          title="ICP not generated yet"
          description="The onboarding agent will generate your ICP once it finishes analyzing your website."
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="card p-6">
        <div className="flex items-start justify-between mb-5">
          <div>
            <h3 className="font-semibold text-ink mb-1">Ideal Customer Profile</h3>
            {icp.confidence_score != null && (
              <p className="text-xs text-ink-muted">
                Confidence score: <span className="font-medium text-ink">{formatPercent(icp.confidence_score)}</span>
              </p>
            )}
          </div>
          {!editing ? (
            <button className="btn-secondary btn-sm" onClick={startEdit}>
              <Edit2 size={13} /> Edit ICP
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

        {/* Missing fields warning */}
        {icp.missing_fields && icp.missing_fields.length > 0 && (
          <div className="mb-4 flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl">
            <AlertCircle size={14} className="text-amber-500 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-700">
              Some fields couldn't be inferred: <span className="font-medium">{icp.missing_fields.join(', ')}</span>.
              You can fill them in by editing the ICP.
            </p>
          </div>
        )}

        {editing ? (
          <EditForm
            draft={draft}
            setField={setField}
            toggleSeniority={toggleSeniority}
            parseList={parseList}
          />
        ) : (
          <ViewForm icp={icp} />
        )}
      </div>
    </div>
  )
}

// ── Read-only view ────────────────────────────────────────────────────────────
function ViewForm({ icp }: { icp: ICPResponse }) {
  const rows = [
    { label: 'Target Type',   value: icp.target_type },
    { label: 'Company Size',  value: companySize(icp.company_size_min, icp.company_size_max) },
    { label: 'Demographics',  value: icp.demographics || '—' },
  ]
  const tagRows = [
    { label: 'Industries',      items: icp.industry },
    { label: 'Job Titles',      items: icp.job_titles },
    { label: 'Seniority',       items: icp.seniority },
    { label: 'Locations',       items: icp.locations },
    { label: 'Funding Status',  items: icp.funding_status },
    { label: 'Tech Stack',      items: icp.tech_stack },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {rows.map(({ label, value }) => (
        <div key={label}>
          <p className="text-xs text-ink-subtle mb-1">{label}</p>
          <p className="text-sm font-medium text-ink capitalize">{value}</p>
        </div>
      ))}
      {tagRows.map(({ label, items }) => (
        <div key={label}>
          <p className="text-xs text-ink-subtle mb-2">{label}</p>
          <TagList items={items} />
        </div>
      ))}
    </div>
  )
}

// ── Edit form ─────────────────────────────────────────────────────────────────
interface EditFormProps {
  draft: UpdateICPRequest
  setField: <K extends keyof UpdateICPRequest>(k: K, v: UpdateICPRequest[K]) => void
  toggleSeniority: (s: Seniority) => void
  parseList: (v: string) => string[]
}

function EditForm({ draft, setField, toggleSeniority, parseList }: EditFormProps) {
  return (
    <div className="space-y-5">
      {/* Target type */}
      <div>
        <label className="label">Target Type</label>
        <div className="flex gap-2">
          {(['business','individual','both'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setField('target_type', t)}
              className={cn(
                'px-3 py-1.5 rounded-lg border text-xs font-medium capitalize transition-all',
                draft.target_type === t
                  ? 'border-brand-500 bg-brand-50 text-brand-700'
                  : 'border-surface-300 text-ink-muted hover:border-brand-300'
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Industries */}
      <div>
        <label className="label">Industries <span className="text-ink-ghost normal-case">(comma-separated)</span></label>
        <input
          className="input"
          value={(draft.industry ?? []).join(', ')}
          onChange={(e) => setField('industry', parseList(e.target.value))}
          placeholder="SaaS, FinTech, E-commerce…"
        />
      </div>

      {/* Company size */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Company Size Min</label>
          <input
            type="number"
            className="input"
            value={draft.company_size_min ?? ''}
            onChange={(e) => setField('company_size_min', e.target.value ? Number(e.target.value) : undefined)}
            placeholder="e.g. 10"
          />
        </div>
        <div>
          <label className="label">Company Size Max</label>
          <input
            type="number"
            className="input"
            value={draft.company_size_max ?? ''}
            onChange={(e) => setField('company_size_max', e.target.value ? Number(e.target.value) : undefined)}
            placeholder="e.g. 500"
          />
        </div>
      </div>

      {/* Job titles */}
      <div>
        <label className="label">Job Titles <span className="text-ink-ghost normal-case">(comma-separated)</span></label>
        <input
          className="input"
          value={(draft.job_titles ?? []).join(', ')}
          onChange={(e) => setField('job_titles', parseList(e.target.value))}
          placeholder="VP of Sales, Head of Growth…"
        />
      </div>

      {/* Seniority */}
      <div>
        <label className="label">Seniority</label>
        <div className="flex flex-wrap gap-2">
          {SENIORITY_OPTIONS.map((s) => {
            const active = ((draft.seniority ?? []) as Seniority[]).includes(s)
            return (
              <button
                key={s}
                type="button"
                onClick={() => toggleSeniority(s)}
                className={cn(
                  'px-2.5 py-1 rounded-lg border text-xs font-medium capitalize transition-all',
                  active
                    ? 'border-brand-500 bg-brand-50 text-brand-700'
                    : 'border-surface-300 text-ink-muted hover:border-brand-300'
                )}
              >
                {s.replace('_', ' ')}
              </button>
            )
          })}
        </div>
      </div>

      {/* Locations */}
      <div>
        <label className="label">Locations <span className="text-ink-ghost normal-case">(comma-separated)</span></label>
        <input
          className="input"
          value={(draft.locations ?? []).join(', ')}
          onChange={(e) => setField('locations', parseList(e.target.value))}
          placeholder="United States, United Kingdom…"
        />
      </div>

      {/* Funding status */}
      <div>
        <label className="label">Funding Status <span className="text-ink-ghost normal-case">(comma-separated)</span></label>
        <input
          className="input"
          value={(draft.funding_status ?? []).join(', ')}
          onChange={(e) => setField('funding_status', parseList(e.target.value))}
          placeholder="Seed, Series A, Bootstrapped…"
        />
      </div>

      {/* Tech stack */}
      <div>
        <label className="label">Tech Stack <span className="text-ink-ghost normal-case">(comma-separated)</span></label>
        <input
          className="input"
          value={(draft.tech_stack ?? []).join(', ')}
          onChange={(e) => setField('tech_stack', parseList(e.target.value))}
          placeholder="React, Salesforce, HubSpot…"
        />
      </div>

      {/* Demographics */}
      <div>
        <label className="label">Demographics / Other</label>
        <textarea
          className="input min-h-[80px] resize-y"
          value={draft.demographics ?? ''}
          onChange={(e) => setField('demographics', e.target.value)}
          placeholder="Any additional demographic or psychographic details…"
        />
      </div>
    </div>
  )
}
