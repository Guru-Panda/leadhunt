import { api } from './client'

export interface Lead {
  id: number
  user_id: number
  strategy_id: number
  source: string
  external_id: string
  person_name: string
  person_title: string | null
  person_location: string | null
  person_linkedin_url: string | null
  person_github_url: string | null
  person_twitter_url: string | null
  person_email: string | null
  email_verified: boolean
  email_source: string | null
  email_confidence: number
  person_phone: string | null
  phone_source: string | null
  is_unlocked: boolean
  source_url: string | null
  source_profile_url: string | null
  source_snippet: string | null
  company_name: string | null
  company_domain: string | null
  company_size: string | null
  company_industry: string | null
  intent_score: number
  intent_signals: string[]
  raw_data: Record<string, unknown>
  outreach_template: string | null
  status: string
  feedback: number | null
  created_at: string
  updated_at: string
}

export interface LeadFilters {
  sources?: string[]
  has_email?: boolean
  email_verified?: boolean
  min_score?: number
  statuses?: string[]
  search?: string
  strategy_id?: number
  skip?: number
  limit?: number
}

export const leadsApi = {
  list: (filters: LeadFilters = {}): Promise<{ data: Lead[] }> => {
    const params = new URLSearchParams()
    if (filters.sources) filters.sources.forEach((s) => params.append('sources', s))
    if (filters.has_email !== undefined) params.set('has_email', String(filters.has_email))
    if (filters.email_verified !== undefined) params.set('email_verified', String(filters.email_verified))
    if (filters.min_score !== undefined) params.set('min_score', String(filters.min_score))
    if (filters.statuses) filters.statuses.forEach((s) => params.append('statuses', s))
    if (filters.search) params.set('search', filters.search)
    if (filters.strategy_id) params.set('strategy_id', String(filters.strategy_id))
    if (filters.skip !== undefined) params.set('skip', String(filters.skip))
    if (filters.limit !== undefined) params.set('limit', String(filters.limit))
    return api.get(`/leads?${params.toString()}`)
  },

  get: (id: number): Promise<{ data: Lead }> => api.get(`/leads/${id}`),

  updateStatus: (id: number, status: string, feedback?: number) =>
    api.patch(`/leads/${id}/status`, { status, feedback }),

  generateOutreach: (id: number): Promise<{ data: { outreach_template: string } }> =>
    api.post(`/leads/${id}/outreach`),

  reEnrich: (id: number): Promise<{ data: Lead }> =>
    api.post(`/leads/${id}/re-enrich`),

  unlock: (id: number): Promise<{ data: { lead: Lead; charged: number; credits_remaining: number; billing_enabled: boolean } }> =>
    api.post(`/leads/${id}/unlock`),

  unwantedCount: (strategy_id: number, scope: 'unwanted' | 'unapproved' = 'unwanted'): Promise<{ data: { count: number } }> =>
    api.get('/leads/unwanted-count', { params: { strategy_id, scope } }),

  purgeUnwanted: (strategy_id: number, scope: 'unwanted' | 'unapproved' = 'unwanted'): Promise<{ data: { deleted: number } }> =>
    api.delete('/leads/purge', { params: { strategy_id, scope } }),

  exportCsvUrl: (filters: LeadFilters = {}) => {
    const base = (import.meta.env.VITE_API_URL || '/api') + '/leads/export-csv'
    const params = new URLSearchParams()
    if (filters.sources) filters.sources.forEach((s) => params.append('sources', s))
    if (filters.has_email !== undefined) params.set('has_email', String(filters.has_email))
    if (filters.email_verified !== undefined) params.set('email_verified', String(filters.email_verified))
    if (filters.min_score !== undefined) params.set('min_score', String(filters.min_score))
    if (filters.statuses) filters.statuses.forEach((s) => params.append('statuses', s))
    if (filters.search) params.set('search', filters.search)
    if (filters.strategy_id) params.set('strategy_id', String(filters.strategy_id))
    return `${base}?${params.toString()}`
  },
}
