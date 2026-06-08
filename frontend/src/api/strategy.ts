import { api } from './client'

export interface Strategy {
  id: number
  user_id: number
  title: string
  main_problem: string
  ideal_customer: string
  keywords: string[]
  buyer_phrases: string[]
  target_locations: string[]
  target_company_size: string[]
  target_roles: string[]
  target_industries: string[]
  competitors: string[] | null
  target_websites: string[]
  event_keywords: string[]
  webinars_enabled: boolean
  events_enabled: boolean
  learning_profile: LearningProfile
  raw_icp_params: Record<string, unknown>
  intent_threshold: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LearningProfile {
  n_approved?: number
  n_rejected?: number
  liked_terms?: string[]
  disliked_terms?: string[]
  liked_sources?: string[]
  disliked_sources?: string[]
  liked_signals?: string[]
  disliked_signals?: string[]
}

export interface StrategyCreate {
  title: string
  main_problem: string
  ideal_customer: string
  keywords: string[]
  buyer_phrases: string[]
  target_locations: string[]
  target_company_size: string[]
  competitors: string[]
  target_websites: string[]
  event_keywords: string[]
  webinars_enabled: boolean
  events_enabled: boolean
  intent_threshold: number
}

export const strategyApi = {
  list: (): Promise<{ data: Strategy[] }> => api.get('/strategies'),
  get: (id: number): Promise<{ data: Strategy }> => api.get(`/strategies/${id}`),
  create: (data: StrategyCreate): Promise<{ data: Strategy }> => api.post('/strategies', data),
  update: (id: number, data: StrategyCreate): Promise<{ data: Strategy }> => api.put(`/strategies/${id}`, data),
  analyze: (id: number): Promise<{ data: Strategy }> => api.post(`/strategies/${id}/analyze`),
  syncNow: (id: number): Promise<{ data: { detail: string } }> => api.post(`/strategies/${id}/sync-now`),
  delete: (id: number) => api.delete(`/strategies/${id}`),
  toggleActive: (id: number): Promise<{ data: Strategy }> => api.post(`/strategies/${id}/toggle-active`),
}
