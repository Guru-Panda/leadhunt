import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Calendar, ExternalLink, Loader2, AlertCircle } from 'lucide-react'
import { leadsApi } from '../api/leads'
import { strategyApi } from '../api/strategy'

export default function OpportunitiesPage() {
  const [strategyId, setStrategyId] = useState<number | undefined>()

  const { data: strategies = [] } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategyApi.list().then((r) => r.data),
  })

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: ['opportunities', strategyId],
    queryFn: () =>
      leadsApi.list({ sources: ['events'], strategy_id: strategyId, limit: 100 }).then((r) => r.data),
  })

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gradient flex items-center gap-2">
            <Calendar className="w-5 h-5 text-primary" /> Opportunities
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Events, webinars & conferences where your buyers gather — attend, sponsor, or speak.
          </p>
        </div>
        <select
          className="input-field w-auto text-sm"
          value={strategyId ?? ''}
          onChange={(e) => setStrategyId(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">All strategies</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>{s.title}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
      ) : isError ? (
        <div className="py-16 text-center">
          <AlertCircle className="w-8 h-8 text-red-400 mb-3 mx-auto" />
          <div className="text-sm font-medium text-gray-700">Couldn't load opportunities</div>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-16 h-16 brand-chip rounded-2xl flex items-center justify-center text-3xl mb-4">📅</div>
          <div className="text-lg font-bold text-gradient mb-1">No opportunities yet</div>
          <div className="text-sm text-gray-500 max-w-xs">
            Run a strategy sync — relevant events & webinars will appear here automatically.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {items.map((ev) => {
            const url = (ev.raw_data?.event_url as string) || ev.source_url || ''
            return (
              <div key={ev.id} className="card flex flex-col">
                <div className="flex items-start gap-2 mb-2">
                  <Calendar className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                  <div className="font-semibold text-gray-900 leading-snug">{ev.person_name}</div>
                </div>
                <p className="text-sm text-gray-600 flex-1 whitespace-pre-wrap">
                  {(ev.source_snippet || '').replace('📅 Event opportunity: ', '').slice(0, 240)}
                </p>
                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
                  >
                    View event <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
