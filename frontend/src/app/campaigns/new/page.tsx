'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Spinner } from '@/components/ui'
import { config } from '@/config'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { ArrowLeft, Globe, Info } from 'lucide-react'
import type { CreateCampaignRequest } from '@/types/api'

type CampaignFormFields = Pick<CreateCampaignRequest, 'name' | 'website_url' | 'company_name'>

export default function NewCampaignPage() {
  const router     = useRouter()
  const { getClient } = useApiClient()

  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState<CampaignFormFields>({
    name: '',
    website_url: '',
    company_name: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const set = <K extends keyof CampaignFormFields>(k: K, v: CampaignFormFields[K]) =>
    setForm((p) => ({ ...p, [k]: v }))

  const validate = () => {
    const e: Record<string, string> = {}
    if (!form.name.trim())        e.name = 'Campaign name is required'
    if (!form.website_url.trim()) e.website_url = 'Website URL is required'
    else if (!/^https?:\/\//i.test(form.website_url)) {
      e.website_url = 'URL must start with http:// or https://'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true)
    try {
      const client = await getClient()
      const payload: CreateCampaignRequest = {
        name: form.name.trim(),
        website_url: form.website_url.trim(),
        company_name: form.company_name?.trim() || null,
        provider: config.campaign.defaultProvider,
        fetch_all: false,
        enrich_mobile: false,
        target_lead_count: config.leads.defaultTargetCount,
      }
      const campaign = await client.createCampaign(payload)
      toast.success('Campaign created — onboarding is running')
      router.push(`/campaigns/${campaign.id}`)
    } catch (err: unknown) {
      const status = (err as { status?: number }).status
      if (status === 402 || status === 403) {
        toast.error('Active subscription required to create campaigns', {
          action: {
            label: 'Subscribe',
            onClick: () => router.push('/billing'),
          },
        })
      } else {
        toast.error('Failed to create campaign')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-8 max-w-2xl mx-auto animate-fade-in">
      {/* Back */}
      <Link href="/campaigns" className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-6 transition-colors">
        <ArrowLeft size={14} /> Back to campaigns
      </Link>

      <h1 className="text-2xl font-semibold text-ink tracking-tight mb-1">New Campaign</h1>
      <p className="text-sm text-ink-muted mb-8">
        Enter your website URL — the AI will scrape it to build your ICP and product brief automatically.
      </p>

      <div className="card p-6 space-y-6">
        {/* Name */}
        <div>
          <label className="label">Campaign Name *</label>
          <input
            className={cn('input', errors.name && 'input-error')}
            placeholder="e.g. Q3 SaaS Outbound"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
          />
          {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
        </div>

        {/* Website URL */}
        <div>
          <label className="label">Company Website URL *</label>
          <div className="relative">
            <Globe size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-ghost" />
            <input
              className={cn('input pl-9', errors.website_url && 'input-error')}
              placeholder="https://yourcompany.com"
              value={form.website_url}
              onChange={(e) => set('website_url', e.target.value)}
            />
          </div>
          {errors.website_url && <p className="text-xs text-red-500 mt-1">{errors.website_url}</p>}
          <p className="text-xs text-ink-subtle mt-1.5 flex items-center gap-1">
            <Info size={11} /> The onboarding agent will scrape this to generate your ICP and product brief.
          </p>
        </div>

        {/* Company name (optional) */}
        <div>
          <label className="label">Company Name <span className="text-ink-ghost normal-case">(optional)</span></label>
          <input
            className="input"
            placeholder="e.g. Acme Inc — inferred from site if blank"
            value={form.company_name || ''}
            onChange={(e) => set('company_name', e.target.value)}
          />
        </div>

        {/* Submit */}
        <div className="flex gap-3 pt-2">
          <Link href="/campaigns" className="btn-secondary flex-1 justify-center">
            Cancel
          </Link>
          <button
            className="btn-primary flex-1"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? <><Spinner size={14} /> Creating…</> : 'Create Campaign'}
          </button>
        </div>
      </div>
    </div>
  )
}
