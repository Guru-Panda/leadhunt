import { api } from './client'

export interface SystemHealth {
  llm: {
    configured: boolean
    providers: string[]
    available: string[]
    rate_limited: boolean
    resets_at: string | null
  }
  search: {
    providers: string[]
    available: string[]
  }
}

export const systemApi = {
  health: (): Promise<{ data: SystemHealth }> => api.get('/system/health'),
}
