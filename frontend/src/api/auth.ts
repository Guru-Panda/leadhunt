import { api } from './client'

export interface User {
  id: number
  email: string
  is_verified: boolean
  full_name: string | null
  role: string | null
  location: string | null
  bio: string | null
  company_name: string | null
  company_website: string | null
  employee_count: string | null
  created_at: string
}

export interface UserUpdate {
  full_name?: string
  role?: string
  location?: string
  bio?: string
  company_name?: string
  company_website?: string
  employee_count?: string
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

  updateMe: (data: UserUpdate): Promise<{ data: User }> =>
    api.patch('/auth/me', data),
}
