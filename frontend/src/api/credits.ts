import { api } from './client'

export interface CreditBalance {
  credits: number
  billing_enabled: boolean
  cost_unlock: number
  cost_export: number
}

export const creditsApi = {
  balance: (): Promise<{ data: CreditBalance }> => api.get('/credits/balance'),
}
