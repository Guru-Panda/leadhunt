import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/analytics'
import { strategyApi } from '../api/strategy'
import { useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { Loader2, Users, MailCheck, MessageCircle, Sparkles } from 'lucide-react'

const PIE_COLORS = ['#6366f1', '#d946ef', '#06b6d4', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#4285f4', '#ff6600', '#ff4500']

const STAT_TONES = {
  purple:  { cls: 'stat-card-purple',  iconCls: 'text-primary',         valueCls: 'text-indigo-900' },
  emerald: { cls: 'stat-card-emerald', iconCls: 'text-emerald-600',     valueCls: 'text-emerald-900' },
  amber:   { cls: 'stat-card-amber',   iconCls: 'text-amber-600',       valueCls: 'text-amber-900' },
  pink:    { cls: 'stat-card-pink',    iconCls: 'text-accent-fuchsia',  valueCls: 'text-fuchsia-900' },
} as const

function StatCard({ label, value, sub, tone, icon: Icon }: {
  label: string; value: string | number; sub?: string;
  tone: keyof typeof STAT_TONES; icon: React.ElementType
}) {
  const t = STAT_TONES[tone]
  return (
    <div className={t.cls}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">{label}</span>
        <Icon className={`w-4 h-4 ${t.iconCls}`} />
      </div>
      <div className={`text-3xl font-bold tabular-nums ${t.valueCls}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

export default function AnalyticsPage() {
  const [strategyId, setStrategyId] = useState<number | undefined>()

  const { data: strategies = [] } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategyApi.list().then((r) => r.data),
  })

  const { data: analytics, isLoading, isError } = useQuery({
    queryKey: ['analytics', strategyId],
    queryFn: () => analyticsApi.get(strategyId).then((r) => r.data),
  })

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gradient">Analytics</h1>
          <p className="text-sm text-gray-500 mt-0.5">Lead pipeline performance</p>
        </div>
        <select
          className="input-field w-auto text-sm"
          value={strategyId ?? ''}
          onChange={(e) => setStrategyId(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">All strategies</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>{s.title}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
        </div>
      ) : isError ? (
        <div className="py-16 text-center">
          <div className="text-sm font-medium text-red-600">Couldn't load analytics</div>
          <div className="text-xs text-gray-500 mt-1">Check your connection and try again.</div>
        </div>
      ) : !analytics ? null : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <StatCard tone="purple"  icon={Users}         label="Total leads"      value={analytics.total_leads.toLocaleString()} />
            <StatCard tone="emerald" icon={MailCheck}     label="Verified emails"  value={`${analytics.verified_email_pct}%`} sub="of all leads" />
            <StatCard tone="amber"   icon={MessageCircle} label="Contacted"        value={`${analytics.contacted_pct}%`} sub="of all leads" />
            <StatCard tone="pink"    icon={Sparkles}      label="Avg intent score" value={`${(analytics.avg_intent_score * 100).toFixed(0)}%`} />
          </div>

          {/* Line chart: leads over time */}
          <div className="card mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Leads over time (last 30 days)</h2>
            {analytics.leads_by_day.length === 0 ? (
              <div className="py-8 text-center text-sm text-gray-400">No data yet</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={analytics.leads_by_day} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="count" stroke="#6366f1" strokeWidth={2} dot={false} name="Leads" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Pie: by source */}
            <div className="card">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Leads by source</h2>
              {analytics.leads_by_source.length === 0 ? (
                <div className="py-8 text-center text-sm text-gray-400">No data yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={analytics.leads_by_source}
                      dataKey="count"
                      nameKey="source"
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      label={({ source, percent }) => `${source} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {analytics.leads_by_source.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => [v, 'Leads']} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Bar: by score bucket */}
            <div className="card">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Leads by intent score</h2>
              {analytics.leads_by_score_bucket.every((b) => b.count === 0) ? (
                <div className="py-8 text-center text-sm text-gray-400">No data yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={analytics.leads_by_score_bucket} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} name="Leads" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
