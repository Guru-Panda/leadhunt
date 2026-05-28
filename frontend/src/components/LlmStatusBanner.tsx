import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { api } from '../api/client'

interface LlmStatus {
  configured: boolean
  rate_limited: boolean
  resets_at: string | null
}

function formatResetTime(iso: string | null): string {
  if (!iso) return 'shortly'
  const resets = new Date(iso)
  const mins = Math.max(0, Math.round((resets.getTime() - Date.now()) / 60000))
  if (mins < 1) return 'any moment'
  if (mins < 60) return `~${mins} min`
  const hrs = Math.round(mins / 60)
  return `~${hrs} hr`
}

export default function LlmStatusBanner() {
  const { data } = useQuery({
    queryKey: ['llm-status'],
    queryFn: () => api.get('/system/llm-status').then((r) => r.data as LlmStatus),
    refetchInterval: 60_000,        // re-check every minute
    refetchOnWindowFocus: true,
    retry: false,
  })

  if (!data?.rate_limited) return null

  return (
    <div className="bg-amber-50 border-b border-amber-200 px-6 py-2.5 flex items-center gap-2 text-sm text-amber-800">
      <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
      <span>
        <span className="font-medium">AI scoring paused</span>
        {' '}— daily quota reached, so leads are being ranked by keyword matching until it resets
        {' '}({formatResetTime(data.resets_at)}). New leads still come in; scores are approximate meanwhile.
      </span>
    </div>
  )
}
