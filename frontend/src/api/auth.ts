import { api } from './client'

export interface User {
  id: number
  email: string
  is_verified: boolean
  company_name: string | null
  employee_count: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

interface OtpSentResponse { detail: string; dev_otp?: string }

export const authApi = {
  signup: (email: string): Promise<{ data: OtpSentResponse }> =>
    api.post('/auth/signup', { email }),

  verifyOtp: (email: string, otp_code: string, password?: string): Promise<{ data: TokenResponse | { detail: string } }> =>
    api.post('/auth/verify-otp', { email, otp_code, password }),

  login: (email: string, password?: string): Promise<{ data: TokenResponse | OtpSentResponse }> =>
    api.post('/auth/login', { email, password }),

  requestOtp: (email: string): Promise<{ data: OtpSentResponse }> =>
    api.post('/auth/request-otp', { email }),

  me: (): Promise<{ data: User }> =>
    api.get('/auth/me'),

  updateMe: (data: { company_name?: string; employee_count?: string }) =>
    api.patch('/auth/me', data),
}
