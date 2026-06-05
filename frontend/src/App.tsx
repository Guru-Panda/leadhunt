import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import StrategyPage from './pages/StrategyPage'
import LeadsPage from './pages/LeadsPage'
import OpportunitiesPage from './pages/OpportunitiesPage'
import MonitorPage from './pages/MonitorPage'
import AnalyticsPage from './pages/AnalyticsPage'
import ProfilePage from './pages/ProfilePage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <div className="flex items-center justify-center h-screen text-gray-400">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AppRoutes() {
  const { user, isLoading } = useAuth()

  if (isLoading) return <div className="flex items-center justify-center h-screen text-gray-400">Loading…</div>

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/leads" replace /> : <LoginPage />} />
      <Route path="/signup" element={user ? <Navigate to="/leads" replace /> : <SignupPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/leads" replace />} />
        <Route path="leads" element={<LeadsPage />} />
        <Route path="opportunities" element={<OpportunitiesPage />} />
        <Route path="strategy" element={<StrategyPage />} />
        <Route path="monitor" element={<MonitorPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/leads" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
