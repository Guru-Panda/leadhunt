import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Crosshair, Loader2, CheckCircle } from 'lucide-react'
import { authApi, type TokenResponse } from '../api/auth'
import { useAuth } from '../context/AuthContext'
import AuthHero from '../components/AuthHero'

type Mode = 'login' | 'reset'           // top-level mode
type Step = 'credentials' | 'otp'       // step within a mode

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [mode, setMode] = useState<Mode>('login')
  const [step, setStep] = useState<Step>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [useOtp, setUseOtp] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [success, setSuccess] = useState('')
  const [devOtp, setDevOtp] = useState('')

  // Toasts driven by URL query (set by signup/reset redirect)
  useEffect(() => {
    if (searchParams.get('signed_up') === '1') {
      setSuccess('Account created! Sign in below with your new password.')
    } else if (searchParams.get('reset') === '1') {
      setSuccess('Password reset! Sign in with your new password.')
    }
  }, [searchParams])

  const resetState = () => {
    setError(''); setInfo(''); setSuccess(''); setOtp(''); setDevOtp('')
    setNewPassword(''); setConfirmPassword('')
  }

  const startResetFlow = () => {
    resetState()
    setMode('reset')
    setStep('credentials')
  }

  const backToLogin = () => {
    resetState()
    setMode('login')
    setStep('credentials')
    setUseOtp(false)
  }

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setSuccess('')
    setLoading(true)
    try {
      // Reset-password mode: just request OTP, then advance to step 2
      if (mode === 'reset') {
        const { data } = await authApi.requestOtp(email)
        if (data?.dev_otp) setDevOtp(data.dev_otp)
        setInfo(`Verification code sent to ${email}.`)
        setStep('otp')
        return
      }

      // Login modes
      if (useOtp) {
        const { data } = await authApi.requestOtp(email)
        if (data?.dev_otp) setDevOtp(data.dev_otp)
        setInfo('Check your email for the verification code.')
        setStep('otp')
      } else {
        const { data } = await authApi.login(email, password)
        if (data && 'access_token' in data) {
          await login(data as TokenResponse)
          navigate('/leads')
        }
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  const handleOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await authApi.verifyOtp(email, otp)
      if ('access_token' in data) {
        await login(data as TokenResponse)
        navigate('/leads')
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Invalid or expired code.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (newPassword.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (newPassword !== confirmPassword) { setError('Passwords do not match.'); return }
    setLoading(true)
    try {
      await authApi.resetPassword(email, otp, newPassword)
      // Back to login mode with success toast
      backToLogin()
      setSuccess('Password reset! Sign in with your new password.')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Invalid or expired code.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      <AuthHero
        title="Welcome back. Your leads are waiting."
        subtitle="Pick up where you left off — your strategies have been hunting in the background."
      />

      <div className="flex-1 md:w-1/2 lg:w-2/5 flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          {/* Mobile-only brand chip */}
          <div className="md:hidden flex items-center gap-2.5 justify-center mb-8">
            <div className="w-9 h-9 brand-chip rounded-lg flex items-center justify-center">
              <Crosshair className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-xl text-gradient">LeadHunt</span>
          </div>

          <div className="card !p-8">
            <h1 className="text-2xl font-bold text-gray-900 mb-1">
              {mode === 'reset'
                ? step === 'otp' ? 'Reset your password 🔐' : 'Forgot password? 🔑'
                : step === 'otp' ? 'Enter your code ✨' : 'Sign in 👋'}
            </h1>
            <p className="text-sm text-gray-500 mb-6">
              {mode === 'reset'
                ? step === 'otp'
                  ? `Enter the code we sent to ${email} and a new password`
                  : "Enter your email — we'll send a code to reset your password"
                : step === 'otp'
                  ? `We sent a 6-digit code to ${email}`
                  : 'Welcome back to LeadHunt'}
            </p>

            {success && (
              <div className="mb-4 px-3 py-2.5 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700 flex items-center gap-2">
                <CheckCircle className="w-4 h-4 shrink-0" /> {success}
              </div>
            )}
            {error && (
              <div className="mb-4 px-3 py-2.5 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600">
                {error}
              </div>
            )}
            {info && (
              <div className="mb-4 px-3 py-2.5 bg-blue-50 border border-blue-100 rounded-lg text-sm text-blue-600">
                {info}
              </div>
            )}
            {devOtp && step === 'otp' && (
              <div className="mb-4 px-3 py-2.5 bg-amber-50 border border-amber-200 rounded-lg text-sm">
                <div className="font-medium text-amber-800 mb-0.5">Dev mode — SMTP not configured</div>
                <div className="text-amber-700">Your code is <span className="font-mono font-semibold tracking-wider">{devOtp}</span></div>
              </div>
            )}

            {/* ── EMAIL STEP (login OR reset) ── */}
            {step === 'credentials' && (
              <form onSubmit={handleCredentials} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Email</label>
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

                {mode === 'login' && !useOtp && (
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="block text-sm font-medium text-gray-700">Password</label>
                      <button type="button" onClick={startResetFlow}
                              className="text-xs text-primary hover:underline">
                        Forgot password?
                      </button>
                    </div>
                    <input
                      type="password"
                      className="input-field"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      autoComplete="current-password"
                    />
                  </div>
                )}

                <button type="submit" className="btn-primary w-full" disabled={loading}>
                  {loading
                    ? <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                    : mode === 'reset'
                      ? 'Send reset code'
                      : useOtp ? 'Send code' : 'Sign in'}
                </button>

                {mode === 'login' ? (
                  <button
                    type="button"
                    onClick={() => { setUseOtp(!useOtp); setError('') }}
                    className="text-sm text-primary hover:underline w-full text-center"
                  >
                    {useOtp ? 'Sign in with password instead' : 'Send me a code instead'}
                  </button>
                ) : (
                  <button type="button" onClick={backToLogin}
                          className="text-sm text-gray-500 hover:underline w-full text-center">
                    Back to sign in
                  </button>
                )}
              </form>
            )}

            {/* ── OTP STEP for LOGIN (sign in via code) ── */}
            {step === 'otp' && mode === 'login' && (
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
                <button type="submit" className="btn-primary w-full" disabled={loading || otp.length < 6}>
                  {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Verify & sign in'}
                </button>
                <button
                  type="button"
                  onClick={() => { setStep('credentials'); setOtp(''); setError('') }}
                  className="text-sm text-gray-500 hover:underline w-full text-center"
                >
                  Back
                </button>
              </form>
            )}

            {/* ── OTP + NEW PASSWORD STEP for RESET ── */}
            {step === 'otp' && mode === 'reset' && (
              <form onSubmit={handleResetPassword} className="space-y-4">
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
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">New password</label>
                  <input
                    type="password"
                    className="input-field"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Confirm new password</label>
                  <input
                    type="password"
                    className="input-field"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </div>
                <button type="submit" className="btn-primary w-full"
                        disabled={loading || otp.length < 6 || newPassword.length < 8 || confirmPassword.length < 8}>
                  {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Reset password'}
                </button>
                <button type="button" onClick={backToLogin}
                        className="text-sm text-gray-500 hover:underline w-full text-center">
                  Back to sign in
                </button>
              </form>
            )}
          </div>

          <p className="text-center text-sm text-gray-500 mt-5">
            No account?{' '}
            <Link to="/signup" className="text-primary hover:underline font-semibold">
              Sign up free
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
