'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { config } from '@/config'
import { useApiClient } from '@/hooks/useApiClient'
import { StatCard, Empty, Spinner } from '@/components/ui'
import { formatDate, statusLabel, campaignStatusColor, cn } from '@/lib/utils'
import type { CampaignResponse, UserResponse } from '@/types/api'
import { Megaphone, Plus, ArrowRight, TrendingUp, Users, Mail, CheckCircle } from 'lucide-react'

export default function DashboardPage() {
  const { getClient } = useApiClient()

  const [user, setUser]           = useState<UserResponse | null>(null)
  const [campaigns, setCampaigns] = useState<CampaignResponse[]>([])
  const [loading, setLoading]     = useState(true)

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const [userRes, campRes] = await Promise.all([
        client.getMe(),
        client.listCampaigns(),
      ])
      setUser(userRes)
      setCampaigns(campRes.campaigns)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [getClient])

  useEffect(() => { load() }, [load])

  // Aggregate stats across all campaigns
  const totals = campaigns.reduce(
    (acc, c) => {
      if (!c.summary) return acc
      acc.leads    += c.summary.total_leads
      acc.approved += c.summary.approved
      acc.emails   += c.summary.emails_written
      return acc
    },
    { leads: 0, approved: 0, emails: 0 }
  )

  const recentCampaigns = [...campaigns]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 5)

  return (
    <div className="p-8 max-w-5xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">
            {loading ? 'Welcome back' : `Welcome back${user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}`}
          </h1>
          <p className="text-sm text-ink-muted mt-1">
            Here's what's happening across your campaigns.
          </p>
        </div>
        <Link href="/campaigns/new" className="btn-primary">
          <Plus size={15} />
          New Campaign
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total Campaigns"
          value={loading ? '—' : campaigns.length}
          loading={loading}
        />
        <StatCard
          label="Leads Processed"
          value={loading ? '—' : totals.leads.toLocaleString()}
          loading={loading}
          accent="text-brand-700"
        />
        <StatCard
          label="Leads Approved"
          value={loading ? '—' : totals.approved.toLocaleString()}
          loading={loading}
          accent="text-status-approved"
        />
        <StatCard
          label="Emails Written"
          value={loading ? '—' : totals.emails.toLocaleString()}
          loading={loading}
          accent="text-brand-600"
        />
      </div>

      {/* Subscription banner */}
      {!loading && user && !user.has_active_subscription && (
        <div className="mb-6 rounded-2xl bg-brand-950 p-5 flex items-center justify-between">
          <div>
            <p className="text-white font-medium text-sm">Upgrade to run campaigns</p>
            <p className="text-brand-300 text-xs mt-0.5">
              Subscribe to the {config.billing.planDisplayName} plan (${config.billing.monthlyPriceUsd}
              /mo) to run the pipeline and generate leads.
            </p>
          </div>
          <Link href={config.billing.path} className="btn-primary btn-sm flex-shrink-0">
            View plans & subscribe
          </Link>
        </div>
      )}

      {/* Recent campaigns */}
      <div className="card">
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-200">
          <h2 className="font-semibold text-ink text-sm">Recent Campaigns</h2>
          <Link href="/campaigns" className="text-xs text-brand-600 hover:text-brand-700 flex items-center gap-1">
            View all <ArrowRight size={12} />
          </Link>
        </div>

        {loading ? (
          <div className="p-6 space-y-3">
            {[1,2,3].map(i => <div key={i} className="skeleton h-14" />)}
          </div>
        ) : recentCampaigns.length === 0 ? (
          <Empty
            icon={<Megaphone size={22} />}
            title="No campaigns yet"
            description="Create your first campaign to start generating and qualifying leads automatically."
            action={
              <Link href="/campaigns/new" className="btn-primary btn-sm">
                <Plus size={13} /> New Campaign
              </Link>
            }
          />
        ) : (
          <div className="divide-y divide-surface-100">
            {recentCampaigns.map((c) => (
              <Link
                key={c.id}
                href={`/campaigns/${c.id}`}
                className="flex items-center justify-between px-6 py-4 hover:bg-surface-50 transition-colors group"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink truncate group-hover:text-brand-700 transition-colors">
                    {c.name}
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={cn('text-xs font-medium', campaignStatusColor(c.status))}>
                      {statusLabel(c.status)}
                    </span>
                    <span className="text-ink-ghost text-xs">·</span>
                    <span className="text-xs text-ink-subtle">{formatDate(c.updated_at)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-6 ml-6 flex-shrink-0">
                  {c.summary && (
                    <div className="hidden sm:flex items-center gap-5 text-xs text-ink-muted">
                      <span className="flex items-center gap-1">
                        <Users size={12} /> {c.summary.total_leads}
                      </span>
                      <span className="flex items-center gap-1 text-status-approved">
                        <CheckCircle size={12} /> {c.summary.approved}
                      </span>
                      <span className="flex items-center gap-1 text-brand-600">
                        <Mail size={12} /> {c.summary.emails_written}
                      </span>
                    </div>
                  )}
                  <ArrowRight size={14} className="text-ink-ghost group-hover:text-brand-600 transition-colors" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Quick tips (only when no campaigns) */}
      {!loading && campaigns.length === 0 && (
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            {
              icon: <TrendingUp size={18} className="text-brand-500" />,
              title: 'Onboarding in seconds',
              desc: 'Enter your website URL and the AI builds your ICP automatically.',
            },
            {
              icon: <Users size={18} className="text-brand-500" />,
              title: 'Qualify at scale',
              desc: 'Enrichment + scoring runs on every lead before you ever open an email.',
            },
            {
              icon: <Mail size={18} className="text-brand-500" />,
              title: 'Ready-to-send sequences',
              desc: 'Personalised 3-email sequences generated for every approved lead.',
            },
          ].map(({ icon, title, desc }) => (
            <div key={title} className="card p-5">
              <div className="w-9 h-9 bg-brand-50 rounded-xl flex items-center justify-center mb-3">
                {icon}
              </div>
              <p className="font-medium text-sm text-ink mb-1">{title}</p>
              <p className="text-xs text-ink-muted leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
