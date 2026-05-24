import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Crosshair, Loader2 } from 'lucide-react'
import { authApi, type TokenResponse } from '../api/auth'
import { useAuth } from '../context/AuthContext'

type Step = 'email' | 'otp'

export default function SignupPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [devOtp, setDevOtp] = useState('')

  const handleEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await authApi.signup(email)
      if (data?.dev_otp) setDevOtp(data.dev_otp)
      setStep('otp')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Failed to send code. Try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await authApi.verifyOtp(email, otp, password || undefined)
      if ('access_token' in data) {
        await login(data as TokenResponse)
        navigate('/strategy')
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Invalid or expired code.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-9 h-9 bg-primary rounded-lg flex items-center justify-center">
            <Crosshair className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-xl text-gray-900">LeadHunt</span>
        </div>

        <div className="card">
          <h1 className="text-lg font-semibold text-gray-900 mb-1">
            {step === 'otp' ? 'Verify your email' : 'Create account'}
          </h1>
          <p className="text-sm text-gray-500 mb-6">
            {step === 'otp'
              ? `Enter the 6-digit code sent to ${email}`
              : 'Start finding leads automatically'}
          </p>

          {error && (
            <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600">
              {error}
            </div>
          )}
          {devOtp && step === 'otp' && (
            <div className="mb-4 px-3 py-2.5 bg-amber-50 border border-amber-200 rounded-lg text-sm">
              <div className="font-medium text-amber-800 mb-0.5">Dev mode — SMTP not configured</div>
              <div className="text-amber-700">Your code is <span className="font-mono font-semibold tracking-wider">{devOtp}</span></div>
            </div>
          )}

          {/* Step indicator */}
          <div className="flex gap-1.5 mb-6">
            {['Email', 'Verify'].map((label, i) => (
              <div key={label} className="flex items-center gap-1.5">
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium ${
                  (step === 'email' && i === 0) || (step === 'otp' && i <= 1)
                    ? 'bg-primary text-white'
                    : 'bg-gray-100 text-gray-400'
                }`}>
                  {i + 1}
                </div>
                <span className={`text-xs ${i === 0 && step === 'email' ? 'text-gray-700' : i === 1 && step === 'otp' ? 'text-gray-700' : 'text-gray-400'}`}>
                  {label}
                </span>
                {i < 1 && <div className="w-4 h-px bg-gray-200 mx-0.5" />}
              </div>
            ))}
          </div>

          {step === 'email' ? (
            <form onSubmit={handleEmail} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Work email</label>
                <input
                  type="email"
                  className="input-field"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  required
                  autoFocus
                />
              </div>
              <button type="submit" className="btn-primary w-full" disabled={loading}>
                {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Send verification code'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleOtp} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Verification code</label>
                <input
                  type="text"
                  className="input-field text-center text-2xl tracking-[0.5em] font-mono"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  maxLength={6}
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Password <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  type="password"
                  className="input-field"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Set a password for future logins"
                />
              </div>
              <button type="submit" className="btn-primary w-full" disabled={loading || otp.length < 6}>
                {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Create account'}
              </button>
              <button
                type="button"
                onClick={() => { setStep('email'); setOtp(''); setError('') }}
                className="text-sm text-gray-500 hover:underline w-full text-center"
              >
                Change email
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-sm text-gray-500 mt-5">
          Already have an account?{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
