import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { Target, Users, Activity, BarChart2, LogOut, Crosshair } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
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
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col bg-white border-r border-gray-200">
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-gray-100">
          <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
            <Crosshair className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-gray-900 text-lg">LeadHunt</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-3 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
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
          <div className="px-3 py-2 text-xs text-gray-500 truncate">{user?.email}</div>
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
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
