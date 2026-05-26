import { Quote } from 'lucide-react'
import type { Lead } from '../api/leads'
import clsx from 'clsx'

interface SignalBlockProps {
  lead: Lead
}

function tone(score: number) {
  if (score >= 0.7) return 'high'
  if (score >= 0.4) return 'medium'
  return 'low'
}

const TONE_STYLES = {
  high: {
    bar:        'bg-green-500',
    barTrack:   'bg-green-100',
    label:      'text-green-700',
    pct:        'text-green-700',
    quoteBox:   'border-green-200 bg-green-50/60',
    quoteText:  'text-green-800',
    quoteHead:  'text-green-700',
  },
  medium: {
    bar:        'bg-amber-500',
    barTrack:   'bg-amber-100',
    label:      'text-amber-700',
    pct:        'text-amber-700',
    quoteBox:   'border-amber-200 bg-amber-50/60',
    quoteText:  'text-amber-800',
    quoteHead:  'text-amber-700',
  },
  low: {
    bar:        'bg-gray-400',
    barTrack:   'bg-gray-100',
    label:      'text-gray-600',
    pct:        'text-gray-600',
    quoteBox:   'border-gray-200 bg-gray-50',
    quoteText:  'text-gray-700',
    quoteHead:  'text-gray-600',
  },
} as const

export default function SignalBlock({ lead }: SignalBlockProps) {
  const raw = (lead.raw_data || {}) as Record<string, unknown>
  const pct = Math.round((lead.intent_score || 0) * 100)
  const t = TONE_STYLES[tone(lead.intent_score || 0)]
  const matchedPhrases = (raw.matched_phrases as string[]) || []
  const matchedKeywords = (raw.matched_keywords as string[]) || []
  const aiSummary = (raw.ai_summary as string) || ''
  const label = (raw.signal_label as string) || ''

  return (
    <div className="space-y-4">
      {/* ── SIGNAL ── */}
      <div>
        <div className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-2">Signal</div>
        <div className="border border-gray-100 rounded-xl p-4 bg-white">
          {/* Score row */}
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-700">Intent score</span>
            <div className="flex items-center gap-2">
              <div className={clsx('w-28 h-1.5 rounded-full overflow-hidden', t.barTrack)}>
                <div className={clsx('h-full transition-all', t.bar)} style={{ width: `${pct}%` }} />
              </div>
              <span className={clsx('text-sm font-bold tabular-nums w-10 text-right', t.pct)}>{pct}%</span>
            </div>
          </div>

          {/* Signal label + matched phrases — green quote box */}
          {(label || matchedPhrases.length > 0) && (
            <div className={clsx('border rounded-lg p-3', t.quoteBox)}>
              {label && (
                <div className={clsx('text-sm font-semibold mb-2', t.label)}>{label}</div>
              )}
              {matchedPhrases.length > 0 && (
                <>
                  <div className={clsx('text-xs font-medium mb-1.5', t.quoteHead)}>
                    Matched buyer phrases:
                  </div>
                  <div className="space-y-1.5">
                    {matchedPhrases.map((phrase, i) => (
                      <div key={i} className="bg-white border border-white/70 rounded px-2.5 py-1.5 flex items-start gap-1.5">
                        <Quote className={clsx('w-3 h-3 mt-1 shrink-0 opacity-50', t.quoteText)} />
                        <span className={clsx('text-sm', t.quoteText)}>{phrase}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── AI SUMMARY ── */}
      {aiSummary && (
        <div>
          <div className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-2">AI Summary</div>
          <div className="border border-gray-100 rounded-xl p-4 bg-white">
            <p className="text-sm text-gray-700 leading-relaxed">{aiSummary}</p>
          </div>
        </div>
      )}

      {/* ── MATCHED KEYWORDS ── */}
      {matchedKeywords.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-2">Matched keywords</div>
          <div className="flex flex-wrap gap-1.5">
            {matchedKeywords.map((kw, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md bg-indigo-50 text-indigo-700 border border-indigo-100 font-medium">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
