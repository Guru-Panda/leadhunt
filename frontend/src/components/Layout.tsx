import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { Target, Users, Activity, BarChart2, LogOut, Crosshair, User as UserIcon } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import OnboardingModal from './OnboardingModal'
import LlmStatusBanner from './LlmStatusBanner'
import clsx from 'clsx'

const NAV = [
  { to: '/leads', icon: Users, label: 'Leads' },
  { to: '/strategy', icon: Target, label: 'Strategy' },
  { to: '/monitor', icon: Activity, label: 'Monitor' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics' },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col sidebar-gradient border-r border-gray-100">
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-gray-100">
          <div className="w-8 h-8 brand-chip rounded-lg flex items-center justify-center">
            <Crosshair className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-gradient text-lg">LeadHunt</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-3 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all',
                  isActive
                    ? 'bg-primary text-white shadow-card'
                    : 'text-gray-600 hover:bg-white/60 hover:text-gray-900'
                )
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User */}
        <div className="px-3 py-4 border-t border-gray-100">
          <NavLink
            to="/profile"
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all w-full mb-1',
                isActive
                  ? 'bg-primary text-white shadow-card'
                  : 'text-gray-700 hover:bg-white/60'
              )
            }
            title="View profile"
          >
            <UserIcon className="w-4 h-4 shrink-0" />
            <span className="flex-1 truncate">
              <span className="block font-medium truncate">
                {user?.full_name || user?.email?.split('@')[0]}
              </span>
              <span className="block text-xs opacity-70 truncate">{user?.email}</span>
            </span>
          </NavLink>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors w-full"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto flex flex-col">
        <LlmStatusBanner />
        <div className="flex-1">
          <Outlet />
        </div>
      </main>

      {/* First-login onboarding nudge */}
      <OnboardingModal />
    </div>
  )
}
