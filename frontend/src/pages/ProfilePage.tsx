import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { User as UserIcon, Building2, Loader2, Check } from 'lucide-react'
import { authApi, type UserUpdate } from '../api/auth'
import { useAuth } from '../context/AuthContext'

const EMPTY: Required<UserUpdate> = {
  full_name: '', role: '', location: '', bio: '',
  company_name: '', company_website: '', employee_count: '',
}

const SIZE_OPTIONS = ['1-10', '11-50', '51-200', '201-1000', '1000+']

export default function ProfilePage() {
  // Use the AuthContext user (works in both real and demo mode)
  const { user, isLoading, refreshUser } = useAuth()

  const [form, setForm] = useState<Required<UserUpdate>>(EMPTY)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (user) {
      setForm({
        full_name: user.full_name ?? '',
        role: user.role ?? '',
        location: user.location ?? '',
        bio: user.bio ?? '',
        company_name: user.company_name ?? '',
        company_website: user.company_website ?? '',
        employee_count: user.employee_count ?? '',
      })
    }
  }, [user])

  const saveMut = useMutation({
    mutationFn: (data: UserUpdate) => authApi.updateMe(data),
    onSuccess: () => {
      refreshUser()  // user lives in AuthContext state, not React Query
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
  })

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    // Send only non-empty fields (so empty inputs don't blank existing values)
    const payload: UserUpdate = {}
    ;(Object.keys(form) as (keyof UserUpdate)[]).forEach((k) => {
      const v = form[k]
      if (typeof v === 'string' && v.trim()) payload[k] = v.trim()
    })
    saveMut.mutate(payload)
  }

  if (isLoading || !user) {
    return (
      <div className="p-6 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gradient">Profile</h1>
        <p className="text-sm text-gray-500 mt-0.5">Your account and company info</p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Account block (read-only email) */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <UserIcon className="w-4 h-4 text-gray-400" />
            <h2 className="text-base font-semibold text-gray-900">Account</h2>
          </div>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Email</label>
              <div className="mt-1 px-3 py-2 bg-gray-50 rounded-lg text-sm text-gray-700">{user.email}</div>
              <p className="text-xs text-gray-400 mt-1">Cannot be changed (used for login)</p>
            </div>
          </div>
        </div>

        {/* Personal block */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <UserIcon className="w-4 h-4 text-gray-400" />
            <h2 className="text-base font-semibold text-gray-900">Personal</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Full name" value={form.full_name}
              onChange={(v) => setForm({ ...form, full_name: v })} placeholder="Jane Doe" />
            <Field label="Role / title" value={form.role}
              onChange={(v) => setForm({ ...form, role: v })} placeholder="Founder" />
            <Field label="Location" value={form.location}
              onChange={(v) => setForm({ ...form, location: v })} placeholder="Bangalore, India" />
          </div>
          <div className="mt-4">
            <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Bio</label>
            <textarea
              value={form.bio}
              onChange={(e) => setForm({ ...form, bio: e.target.value })}
              placeholder="One-liner about you"
              rows={2}
              className="input-field mt-1 w-full"
            />
          </div>
        </div>

        {/* Company block */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Building2 className="w-4 h-4 text-gray-400" />
            <h2 className="text-base font-semibold text-gray-900">Company</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Company name" value={form.company_name}
              onChange={(v) => setForm({ ...form, company_name: v })} placeholder="Acme Inc" />
            <Field label="Website" value={form.company_website}
              onChange={(v) => setForm({ ...form, company_website: v })} placeholder="https://acme.com" />
          </div>
          <div className="mt-4">
            <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Employee count</label>
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
        </div>

        {/* Save */}
        <div className="flex items-center gap-3">
          <button type="submit" className="btn-primary flex items-center gap-2" disabled={saveMut.isPending}>
            {saveMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Save changes
          </button>
          {saved && (
            <span className="text-sm text-green-600 flex items-center gap-1">
              <Check className="w-4 h-4" /> Saved
            </span>
          )}
          {saveMut.isError && (
            <span className="text-sm text-red-600">Save failed — try again</span>
          )}
        </div>
      </form>
    </div>
  )
}

function Field({ label, value, onChange, placeholder }: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <div>
      <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input-field mt-1 w-full"
      />
    </div>
  )
}
