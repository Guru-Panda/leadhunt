import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/analytics'
import { strategyApi } from '../api/strategy'
import { useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { Loader2 } from 'lucide-react'

const PIE_COLORS = ['#6366f1', '#f26625', '#24292e', '#ff6600', '#ff4500', '#003a9b', '#000', '#4285f4', '#8b5cf6', '#6b7280']

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card text-center">
      <div className="text-3xl font-bold text-gray-900">{value}</div>
      <div className="text-sm font-medium text-gray-700 mt-1">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function AnalyticsPage() {
  const [strategyId, setStrategyId] = useState<number | undefined>()

  const { data: strategies = [] } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategyApi.list().then((r) => r.data),
  })

  const { data: analytics, isLoading } = useQuery({
    queryKey: ['analytics', strategyId],
    queryFn: () => analyticsApi.get(strategyId).then((r) => r.data),
  })

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Analytics</h1>
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
      ) : !analytics ? null : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-4 gap-4 mb-6">
            <StatCard label="Total leads" value={analytics.total_leads.toLocaleString()} />
            <StatCard label="Verified emails" value={`${analytics.verified_email_pct}%`} sub="of all leads" />
            <StatCard label="Contacted" value={`${analytics.contacted_pct}%`} sub="of all leads" />
            <StatCard label="Avg intent score" value={`${(analytics.avg_intent_score * 100).toFixed(0)}%`} />
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
