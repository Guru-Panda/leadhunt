import { api } from './client'

export interface Analytics {
  total_leads: number
  verified_email_pct: number
  contacted_pct: number
  avg_intent_score: number
  leads_by_day: { date: string; count: number }[]
  leads_by_source: { source: string; count: number }[]
  leads_by_score_bucket: { bucket: string; count: number }[]
}

export const analyticsApi = {
  get: (strategy_id?: number): Promise<{ data: Analytics }> =>
    api.get('/analytics', { params: strategy_id ? { strategy_id } : {} }),
}
