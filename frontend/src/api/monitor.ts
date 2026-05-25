import { api } from './client'

export interface SyncRun {
  id: number
  strategy_id: number
  source: string
  status: string
  leads_found: number
  started_at: string
  finished_at: string | null
  error: string | null
}

export interface DiscoveredSource {
  id: number
  strategy_id: number
  name: string
  type: string
  url_pattern: string
  access_method: string
  status: string
  leads_found_total: number
  runs: number
  success_rate: number
  last_run_at: string | null
  last_error: string | null
  created_at: string
}

export interface SourceStat {
  source: string
  total_leads: number
  with_email: number
  verified_email: number
  avg_score: number
  last_run_at: string | null
  last_status: string
  last_error: string | null
  last_leads_found: number
}

export const monitorApi = {
  sourceStats: (strategy_id?: number): Promise<{ data: SourceStat[] }> =>
    api.get('/monitor/source-stats', { params: strategy_id ? { strategy_id } : {} }),
  syncRuns: (strategy_id?: number): Promise<{ data: SyncRun[] }> =>
    api.get('/monitor/sync-runs', { params: strategy_id ? { strategy_id } : {} }),

  discoveredSources: (strategy_id?: number): Promise<{ data: DiscoveredSource[] }> =>
    api.get('/monitor/discovered-sources', { params: strategy_id ? { strategy_id } : {} }),

  toggleSource: (id: number): Promise<{ data: DiscoveredSource }> =>
    api.patch(`/monitor/discovered-sources/${id}/toggle`),

  deleteSource: (id: number) =>
    api.delete(`/monitor/discovered-sources/${id}`),

  cleanupBroken: (strategy_id?: number): Promise<{ data: { deleted: number } }> =>
    api.delete('/monitor/discovered-sources/cleanup-broken', { params: strategy_id ? { strategy_id } : {} }),

  retestSource: (id: number) =>
    api.post(`/monitor/discovered-sources/${id}/retest`),

  triggerDiscovery: (strategy_id: number) =>
    api.post('/monitor/discover', null, { params: { strategy_id } }),

  addCustomUrl: (url: string, strategy_id: number): Promise<{ data: DiscoveredSource }> =>
    api.post('/monitor/add-custom-url', { url, strategy_id }),
}
