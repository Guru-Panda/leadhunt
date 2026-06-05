import { useQuery } from '@tanstack/react-query'
import { Cpu, Search } from 'lucide-react'
import clsx from 'clsx'
import { systemApi } from '../api/system'

function ProviderChips({ all, available }: { all: string[]; available: string[] }) {
  if (!all.length) return <span className="text-xs text-gray-400">none configured</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {all.map((p) => {
        const up = available.includes(p)
        return (
          <span
            key={p}
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border inline-flex items-center',
              up ? 'bg-green-50 text-green-700 border-green-100' : 'bg-amber-50 text-amber-700 border-amber-100'
            )}
            title={up ? 'available' : 'cooling down (rate-limited)'}
          >
            <span className={clsx('inline-block w-1.5 h-1.5 rounded-full mr-1', up ? 'bg-green-500' : 'bg-amber-500')} />
            {p}
          </span>
        )
      })}
    </div>
  )
}

export default function SystemHealth() {
  const { data } = useQuery({
    queryKey: ['system-health'],
    queryFn: () => systemApi.health().then((r) => r.data),
    refetchInterval: 30_000,
  })
  if (!data) return null
  return (
    <div className="card mb-6">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Provider health</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
            <Cpu className="w-4 h-4 text-primary" /> LLM pool
            {data.llm.rate_limited && <span className="text-xs text-amber-600">(all cooling down)</span>}
          </div>
          <ProviderChips all={data.llm.providers} available={data.llm.available} />
        </div>
        <div>
          <div className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
            <Search className="w-4 h-4 text-primary" /> Search pool
          </div>
          <ProviderChips all={data.search.providers} available={data.search.available} />
        </div>
      </div>
    </div>
  )
}
