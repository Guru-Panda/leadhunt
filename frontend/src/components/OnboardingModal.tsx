import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { X, Loader2, Sparkles } from 'lucide-react'
import { authApi, type UserUpdate } from '../api/auth'
import { useAuth } from '../context/AuthContext'

const DISMISS_KEY = 'leadhunt_onboarding_dismissed'

const SIZE_OPTIONS = ['1-10', '11-50', '51-200', '201-1000', '1000+']

export default function OnboardingModal() {
  const { user, refreshUser } = useAuth()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    full_name: '', role: '', company_name: '', company_website: '', employee_count: '',
  })

  // Only show if user has NO full_name AND hasn't dismissed before
  useEffect(() => {
    if (!user) return
    const dismissed = sessionStorage.getItem(DISMISS_KEY) === '1'
    if (!user.full_name && !dismissed) setOpen(true)
  }, [user])

  const saveMut = useMutation({
    mutationFn: (data: UserUpdate) => authApi.updateMe(data),
    onSuccess: () => {
      refreshUser()  // user lives in AuthContext state, not React Query
      setOpen(false)
    },
  })

  if (!open || !user) return null

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: UserUpdate = {}
    Object.entries(form).forEach(([k, v]) => {
      if (v.trim()) (payload as Record<string, string>)[k] = v.trim()
    })
    if (Object.keys(payload).length === 0) return handleSkip()
    saveMut.mutate(payload)
  }

  const handleSkip = () => {
    sessionStorage.setItem(DISMISS_KEY, '1')
    setOpen(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full">
        <div className="flex items-start justify-between p-5 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Welcome to LeadHunt!</h2>
              <p className="text-xs text-gray-500 mt-0.5">Tell us a bit about you — takes 30 seconds.</p>
            </div>
          </div>
          <button onClick={handleSkip} className="text-gray-400 hover:text-gray-600" title="Skip for now">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSave} className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Full name</label>
              <input
                type="text"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Jane Doe"
                className="input-field mt-1 w-full"
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Your role</label>
              <input
                type="text"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                placeholder="Founder"
                className="input-field mt-1 w-full"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Company name</label>
              <input
                type="text"
                value={form.company_name}
                onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                placeholder="Acme Inc"
                className="input-field mt-1 w-full"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Website</label>
              <input
                type="text"
                value={form.company_website}
                onChange={(e) => setForm({ ...form, company_website: e.target.value })}
                placeholder="https://acme.com"
                className="input-field mt-1 w-full"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Company size</label>
            <div className="mt-2 flex flex-wrap gap-2">
              {SIZE_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setForm({ ...form, employee_count: opt === form.employee_count ? '' : opt })}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    form.employee_count === opt
                      ? 'bg-primary text-white border-primary'
                      : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
            <button type="button" onClick={handleSkip} className="btn-secondary text-sm">
              Skip for now
            </button>
            <button type="submit" className="btn-primary text-sm flex items-center gap-1.5" disabled={saveMut.isPending}>
              {saveMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              Save
            </button>
          </div>
          <p className="text-xs text-gray-400">You can always edit these on your Profile page.</p>
        </form>
      </div>
    </div>
  )
}
