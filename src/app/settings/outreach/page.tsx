'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Spinner } from '@/components/ui'
import { formatApiError } from '@/lib/utils'
import type { OutreachSettingsRequest } from '@/types/api'
import { toast } from 'sonner'
import { ArrowLeft, Send, ShieldCheck, KeyRound } from 'lucide-react'

export default function OutreachSettingsPage() {
  const { getClient } = useApiClient()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<OutreachSettingsRequest>({
    resend_api_key: '',
    sending_domain: '',
    sending_email: '',
    sending_name: '',
    cal_link: '',
  })

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const s = await client.getOutreachSettings()
      setForm((p) => ({
        ...p,
        resend_api_key: '',
        sending_domain: s.sending_domain ?? '',
        sending_email: s.sending_email ?? '',
        sending_name: s.sending_name ?? '',
        cal_link: s.cal_link ?? '',
      }))
    } catch {
      toast.error('Failed to load sending settings')
    } finally {
      setLoading(false)
    }
  }, [getClient])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    if (!form.resend_api_key.trim()) {
      toast.error('Paste your Resend API key to save. The key is not shown again after you leave this page.')
      return
    }
    if (!form.sending_domain.trim() || !form.sending_email.trim() || !form.sending_name.trim()) {
      toast.error('Domain, from email, and sender name are required.')
      return
    }
    setSaving(true)
    try {
      const client = await getClient()
      await client.updateOutreachSettings({
        resend_api_key: form.resend_api_key.trim(),
        sending_domain: form.sending_domain.trim(),
        sending_email: form.sending_email.trim(),
        sending_name: form.sending_name.trim(),
        cal_link: form.cal_link?.trim() || null,
      })
      setForm((p) => ({ ...p, resend_api_key: '' }))
      toast.success('Sending settings saved')
      await load()
    } catch (e) {
      toast.error(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 max-w-2xl mx-auto flex justify-center py-24">
        <Spinner size={28} />
      </div>
    )
  }

  return (
    <div className="p-8 max-w-2xl mx-auto animate-fade-in">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-5 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      <div className="flex items-start gap-4 mb-8">
        <div className="w-12 h-12 rounded-2xl bg-brand-100 flex items-center justify-center flex-shrink-0">
          <Send size={22} className="text-brand-700" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">Email sending</h1>
          <p className="text-sm text-ink-muted mt-1 max-w-lg">
            Connect your Resend account so you can send sequences from your own domain. Keys stay on your account — we never send from a shared platform address.
          </p>
        </div>
      </div>

      <div className="rounded-2xl bg-brand-950 p-5 mb-6 flex gap-3">
        <ShieldCheck size={20} className="text-brand-300 flex-shrink-0 mt-0.5" />
        <p className="text-sm text-brand-200 leading-relaxed">
          Resend does not return your API key to the app. Paste it every time you save — that is how the server confirms the right key. After saving, open a campaign, review the three emails, and use <strong className="text-white">Send first email</strong> on the sequence page.
        </p>
      </div>

      <div className="card p-6 space-y-5">
        <div>
          <label className="label flex items-center gap-2">
            <KeyRound size={12} /> Resend API key
          </label>
          <input
            type="password"
            autoComplete="off"
            className="input font-mono text-xs"
            placeholder="re_…"
            value={form.resend_api_key}
            onChange={(e) => setForm((p) => ({ ...p, resend_api_key: e.target.value }))}
          />
          <p className="text-[11px] text-ink-subtle mt-1.5">
            Required on every save. Get it from the Resend dashboard.
          </p>
        </div>

        <div>
          <label className="label">Verified sending domain</label>
          <input
            className="input"
            placeholder="yourcompany.com"
            value={form.sending_domain}
            onChange={(e) => setForm((p) => ({ ...p, sending_domain: e.target.value }))}
          />
        </div>

        <div>
          <label className="label">From email</label>
          <input
            type="email"
            className="input"
            placeholder="you@yourcompany.com"
            value={form.sending_email}
            onChange={(e) => setForm((p) => ({ ...p, sending_email: e.target.value }))}
          />
        </div>

        <div>
          <label className="label">Sender display name</label>
          <input
            className="input"
            placeholder="Alex from Acme"
            value={form.sending_name}
            onChange={(e) => setForm((p) => ({ ...p, sending_name: e.target.value }))}
          />
        </div>

        <div>
          <label className="label">Cal.com booking link (optional)</label>
          <input
            className="input"
            placeholder="https://cal.com/your-org/discovery"
            value={form.cal_link ?? ''}
            onChange={(e) => setForm((p) => ({ ...p, cal_link: e.target.value }))}
          />
          <p className="text-[11px] text-ink-subtle mt-1.5">
            Used when the reply agent drafts a response for interested leads.
          </p>
        </div>

        <div className="pt-2 flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={load} disabled={saving}>
            Reload
          </button>
          <button type="button" className="btn-primary min-w-[140px]" onClick={save} disabled={saving}>
            {saving ? <Spinner size={16} /> : null}
            Save settings
          </button>
        </div>
      </div>
    </div>
  )
}
