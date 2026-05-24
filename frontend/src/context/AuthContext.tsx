import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { authApi, type User } from '../api/auth'

interface AuthState {
  user: User | null
  isLoading: boolean
  login: (tokens: { access_token: string; refresh_token: string }) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchMe = useCallback(async () => {
    // Demo mode: ?demo=true skips the API call
    if (new URLSearchParams(window.location.search).get('demo') === 'true') {
      setUser({ id: 0, email: 'demo@leadhunt.io', is_verified: true, company_name: 'Acme Corp', employee_count: '11-50', created_at: new Date().toISOString() })
      setIsLoading(false)
      return
    }
    const token = localStorage.getItem('access_token')
    if (!token) {
      setIsLoading(false)
      return
    }
    try {
      const { data } = await authApi.me()
      setUser(data)
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMe()
  }, [fetchMe])

  const login = async (tokens: { access_token: string; refresh_token: string }) => {
    localStorage.setItem('access_token', tokens.access_token)
    localStorage.setItem('refresh_token', tokens.refresh_token)
    const { data } = await authApi.me()
    setUser(data)
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
