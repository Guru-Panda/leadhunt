import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, RefreshCw, Trash2, Plus, Loader2, ExternalLink,
  CheckCircle, XCircle, Clock, AlertTriangle, Zap, Mail
} from 'lucide-react'
import { monitorApi, type DiscoveredSource, type SourceStat } from '../api/monitor'
import { strategyApi } from '../api/strategy'
import SourceBadge from '../components/SourceBadge'
import clsx from 'clsx'

const STATUS_ICONS: Record<string, React.ReactNode> = {
  ok: <CheckCircle className="w-4 h-4 text-green-500" />,
  error: <XCircle className="w-4 h-4 text-red-500" />,
  running: <Loader2 className="w-4 h-4 animate-spin text-blue-500" />,
  active: <CheckCircle className="w-4 h-4 text-green-500" />,
  pending: <Clock className="w-4 h-4 text-yellow-500" />,
  broken: <AlertTriangle className="w-4 h-4 text-red-500" />,
  rejected: <XCircle className="w-4 h-4 text-gray-400" />,
}

export default function MonitorPage() {
  const qc = useQueryClient()
  const [strategyId, setStrategyId] = useState<number | undefined>()
  const [customUrl, setCustomUrl] = useState('')
  const [addingUrl, setAddingUrl] = useState(false)
  const [urlError, setUrlError] = useState('')

  const { data: strategies = [] } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategyApi.list().then((r) => r.data),
  })

  const { data: sourceStats = [], isLoading: statsLoading } = useQuery({
    queryKey: ['source-stats', strategyId],
    queryFn: () => monitorApi.sourceStats(strategyId).then((r) => r.data),
    refetchInterval: 30_000,
  })

  const { data: discovered = [], isLoading: discLoading } = useQuery({
    queryKey: ['discovered-sources', strategyId],
    queryFn: () => monitorApi.discoveredSources(strategyId).then((r) => r.data),
    refetchInterval: 30_000,
  })

  const toggleMut = useMutation({
    mutationFn: monitorApi.toggleSource,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovered-sources'] }),
  })

  const deleteMut = useMutation({
    mutationFn: monitorApi.deleteSource,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovered-sources'] }),
  })

  const retestMut = useMutation({
    mutationFn: monitorApi.retestSource,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovered-sources'] }),
  })

  const discoverMut = useMutation({
    mutationFn: monitorApi.triggerDiscovery,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovered-sources'] })
    },
  })

  const syncNowMut = useMutation({
    mutationFn: strategyApi.syncNow,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['source-stats'] })
    },
  })

  const addUrlMut = useMutation({
    mutationFn: ({ url, strategy_id }: { url: string; strategy_id: number }) =>
      monitorApi.addCustomUrl(url, strategy_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovered-sources'] })
      setCustomUrl('')
      setAddingUrl(false)
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUrlError(msg || 'Failed to add URL')
    },
  })

  // Filter out discovered: sources from base sources table
  const baseSources = sourceStats.filter((s) => !s.source.startsWith('discovered:'))
                                 .sort((a, b) => b.total_leads - a.total_leads || a.source.localeCompare(b.source))

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Monitor</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track source health and discovered leads</p>
        </div>
        <div className="flex items-center gap-3">
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
          {strategyId && (
            <>
              <button
                onClick={() => syncNowMut.mutate(strategyId)}
                disabled={syncNowMut.isPending}
                className="btn-primary flex items-center gap-2 text-sm"
              >
                {syncNowMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                Sync now
              </button>
              <button
                onClick={() => discoverMut.mutate(strategyId)}
                disabled={discoverMut.isPending}
                className="btn-secondary flex items-center gap-2 text-sm"
              >
                {discoverMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                Discover sources
              </button>
            </>
          )}
        </div>
      </div>

      {/* Base sources table — per-source health snapshot */}
      <div className="card mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Base sources</h2>
        {statsLoading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
        ) : baseSources.length === 0 ? (
          <div className="py-6 text-center text-sm text-gray-400">No sync runs yet. Create a strategy and click "Sync now" to start.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Source</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Leads</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Emails</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Avg score</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Last run</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {baseSources.map((stat: SourceStat) => {
                  const emailPct = stat.total_leads ? Math.round((stat.with_email / stat.total_leads) * 100) : 0
                  return (
                    <tr key={stat.source}>
                      <td className="py-2.5"><SourceBadge source={stat.source} /></td>
                      <td className="py-2.5 text-right font-medium text-gray-900">{stat.total_leads}</td>
                      <td className="py-2.5 text-right">
                        {stat.with_email > 0 ? (
                          <span className="inline-flex items-center gap-1 text-xs">
                            <Mail className="w-3 h-3 text-green-500" />
                            <span className="text-gray-900 font-medium">{stat.with_email}</span>
                            <span className="text-gray-400">({emailPct}%)</span>
                          </span>
                        ) : (
                          <span className="text-xs text-gray-300">—</span>
                        )}
                      </td>
                      <td className="py-2.5 text-right text-gray-600">
                        {stat.avg_score ? `${Math.round(stat.avg_score * 100)}%` : '—'}
                      </td>
                      <td className="py-2.5 text-xs text-gray-500">
                        {stat.last_run_at ? new Date(stat.last_run_at).toLocaleString() : 'never'}
                      </td>
                      <td className="py-2.5">
                        <div className="flex items-center gap-1.5">
                          {STATUS_ICONS[stat.last_status] || <Clock className="w-4 h-4 text-gray-400" />}
                          <span className="text-xs text-gray-600 capitalize">{stat.last_status.replace('_', ' ')}</span>
                          {stat.last_error && (
                            <span className="text-xs text-red-500 truncate max-w-[160px]" title={stat.last_error}>— {stat.last_error}</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Discovered sources */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Discovered sources</h2>
          <button
            onClick={() => { setAddingUrl(!addingUrl); setUrlError('') }}
            className="btn-secondary flex items-center gap-1.5 text-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add custom URL
          </button>
        </div>

        {addingUrl && strategyId && (
          <div className="mb-4 p-3 bg-gray-50 rounded-lg">
            <div className="flex gap-2">
              <input
                type="url"
                className="input-field flex-1"
                placeholder="https://example.com/people"
                value={customUrl}
                onChange={(e) => { setCustomUrl(e.target.value); setUrlError('') }}
              />
              <button
                onClick={() => addUrlMut.mutate({ url: customUrl, strategy_id: strategyId })}
                disabled={!customUrl || addUrlMut.isPending}
                className="btn-primary text-sm px-4"
              >
                {addUrlMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Test & add'}
              </button>
            </div>
            {urlError && <p className="text-xs text-red-500 mt-1.5">{urlError}</p>}
            {!strategyId && <p className="text-xs text-gray-400 mt-1">Select a strategy first</p>}
          </div>
        )}
        {addingUrl && !strategyId && (
          <div className="mb-4 px-3 py-2 bg-yellow-50 border border-yellow-100 rounded-lg text-sm text-yellow-700">
            Select a strategy above first to add a custom URL.
          </div>
        )}

        {discLoading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
        ) : discovered.length === 0 ? (
          <div className="py-6 text-center text-sm text-gray-400">
            No discovered sources yet. Click "Discover new sources" after selecting a strategy.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Name</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Type</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Runs</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Leads</th>
                  <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Rate</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">Last run</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {discovered.map((ds) => (
                  <tr key={ds.id}>
                    <td className="py-2.5">
                      <a href={ds.url_pattern} target="_blank" rel="noopener noreferrer"
                        className="font-medium text-gray-900 hover:text-primary flex items-center gap-1">
                        {ds.name}
                        <ExternalLink className="w-3 h-3 text-gray-300" />
                      </a>
                    </td>
                    <td className="py-2.5">
                      <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">{ds.type}</span>
                    </td>
                    <td className="py-2.5">
                      <div className="flex items-center gap-1.5">
                        {STATUS_ICONS[ds.status] || <Clock className="w-4 h-4 text-gray-400" />}
                        <span className="text-xs capitalize text-gray-600">{ds.status}</span>
                      </div>
                    </td>
                    <td className="py-2.5 text-right text-gray-500">{ds.runs}</td>
                    <td className="py-2.5 text-right font-medium text-gray-900">{ds.leads_found_total}</td>
                    <td className="py-2.5 text-right text-gray-500">{ds.success_rate.toFixed(1)}</td>
                    <td className="py-2.5 text-xs text-gray-400">
                      {ds.last_run_at ? new Date(ds.last_run_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-2.5">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => retestMut.mutate(ds.id)}
                          className="p-1 text-gray-400 hover:text-primary transition-colors" title="Re-test"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => toggleMut.mutate(ds.id)}
                          className={clsx('p-1 transition-colors', ds.status === 'active' ? 'text-green-500 hover:text-green-700' : 'text-gray-400 hover:text-gray-600')}
                          title="Toggle active"
                        >
                          <Activity className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => { if (confirm('Delete this source?')) deleteMut.mutate(ds.id) }}
                          className="p-1 text-gray-400 hover:text-red-500 transition-colors" title="Delete"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
