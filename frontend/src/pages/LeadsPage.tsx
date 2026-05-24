import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search, Download, Mail, CheckCircle, AlertCircle, ExternalLink,
  Github, Linkedin, Twitter, Eye, MessageSquare, ThumbsUp, ThumbsDown,
  ChevronDown, Loader2, X, Quote, Link as LinkIcon, User as UserIcon, Sparkles
} from 'lucide-react'
import { leadsApi, type Lead, type LeadFilters } from '../api/leads'
import SourceBadge from '../components/SourceBadge'
import clsx from 'clsx'

const STATUS_COLORS: Record<string, string> = {
  new: 'bg-blue-50 text-blue-700',
  contacted: 'bg-yellow-50 text-yellow-700',
  qualified: 'bg-green-50 text-green-700',
  rejected: 'bg-red-50 text-red-700',
  ignored: 'bg-gray-50 text-gray-500',
}

const EMAIL_SOURCE_LABEL: Record<string, { text: string; tone: 'high' | 'medium' | 'low' }> = {
  source_text:   { text: 'Posted publicly',    tone: 'high' },
  company_site:  { text: 'Company site',       tone: 'high' },
  github_commit: { text: 'GitHub commits',     tone: 'high' },
  hunter:        { text: 'Hunter.io',          tone: 'high' },
  whois:         { text: 'WHOIS registrant',   tone: 'medium' },
  pattern_guess: { text: 'Pattern guess',      tone: 'low' },
}

export default function LeadsPage() {
  const qc = useQueryClient()
  const [filters, setFilters] = useState<LeadFilters>({ limit: 100 })
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Lead | null>(null)
  const [outreachText, setOutreachText] = useState('')

  const { data: leads = [], isLoading } = useQuery({
    queryKey: ['leads', filters, search],
    queryFn: () => leadsApi.list({ ...filters, search: search || undefined }).then((r) => r.data),
  })

  const statusMut = useMutation({
    mutationFn: ({ id, status, feedback }: { id: number; status: string; feedback?: number }) =>
      leadsApi.updateStatus(id, status, feedback),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['leads'] }),
  })

  const outreachMut = useMutation({
    mutationFn: (id: number) => leadsApi.generateOutreach(id),
    onSuccess: (r) => setOutreachText(r.data.outreach_template),
  })

  const reEnrichMut = useMutation({
    mutationFn: (id: number) => leadsApi.reEnrich(id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['leads'] })
      if (selected && selected.id === r.data.id) setSelected(r.data)
    },
  })

  const handleExportCsv = () => {
    const url = leadsApi.exportCsvUrl({ ...filters, search: search || undefined })
    const token = localStorage.getItem('access_token')
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'leads.csv'
        a.click()
      })
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-200 bg-white shrink-0">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              className="input-field pl-9"
              placeholder="Search leads…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {/* Filters */}
          <select
            className="input-field w-auto text-sm"
            onChange={(e) => setFilters((f) => ({ ...f, has_email: e.target.value === '' ? undefined : e.target.value === 'true' }))}
          >
            <option value="">All leads</option>
            <option value="true">Has email</option>
            <option value="false">No email</option>
          </select>

          <select
            className="input-field w-auto text-sm"
            onChange={(e) => setFilters((f) => ({ ...f, email_verified: e.target.value === '' ? undefined : e.target.value === 'true' }))}
          >
            <option value="">Any email</option>
            <option value="true">Verified email</option>
            <option value="false">Unverified</option>
          </select>

          <select
            className="input-field w-auto text-sm"
            onChange={(e) => setFilters((f) => ({ ...f, statuses: e.target.value ? [e.target.value] : undefined }))}
          >
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="contacted">Contacted</option>
            <option value="qualified">Qualified</option>
            <option value="rejected">Rejected</option>
          </select>

          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">Min score</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={filters.min_score ?? 0}
              onChange={(e) => {
                const v = parseFloat(e.target.value)
                setFilters((f) => ({ ...f, min_score: v > 0 ? v : undefined }))
              }}
              className="w-20 accent-primary"
            />
            <span className="text-xs text-gray-500 tabular-nums w-7">
              {filters.min_score !== undefined ? `${Math.round(filters.min_score * 100)}%` : '—'}
            </span>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-gray-500">
              {leads.length} leads
              {leads.length > 0 && (() => {
                const withEmail = leads.filter((l) => l.person_email).length
                const verified = leads.filter((l) => l.email_verified).length
                return (
                  <>
                    {' · '}
                    <span className="text-green-600 font-medium">{verified} verified</span>
                    {' · '}
                    <span className="text-gray-600">{withEmail - verified} unverified</span>
                  </>
                )
              })()}
            </span>
            <button onClick={handleExportCsv} className="btn-secondary flex items-center gap-1.5 text-sm">
              <Download className="w-3.5 h-3.5" /> Export CSV
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          ) : leads.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="text-4xl mb-3">🎯</div>
              <div className="font-medium text-gray-900 mb-1">No leads yet</div>
              <div className="text-sm text-gray-500">Create a strategy and leads will appear here automatically</div>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Person</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Company</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Source</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Email</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Score</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {leads.map((lead) => (
                  <LeadRow
                    key={lead.id}
                    lead={lead}
                    onView={() => { setSelected(lead); setOutreachText(lead.outreach_template || '') }}
                    onStatusChange={(status, feedback) => statusMut.mutate({ id: lead.id, status, feedback })}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <LeadDrawer
          lead={selected}
          outreachText={outreachText}
          setOutreachText={setOutreachText}
          onClose={() => setSelected(null)}
          onGenerateOutreach={() => outreachMut.mutate(selected.id)}
          generatingOutreach={outreachMut.isPending}
          onStatusChange={(status, feedback) => {
            statusMut.mutate({ id: selected.id, status, feedback })
            setSelected({ ...selected, status, feedback: feedback ?? selected.feedback })
          }}
          onReEnrich={() => reEnrichMut.mutate(selected.id)}
          reEnriching={reEnrichMut.isPending}
        />
      )}
    </div>
  )
}

function LeadRow({ lead, onView, onStatusChange }: {
  lead: Lead
  onView: () => void
  onStatusChange: (status: string, feedback?: number) => void
}) {
  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900">{lead.person_name}</div>
        {lead.person_title && <div className="text-xs text-gray-500 mt-0.5 truncate max-w-[160px]">{lead.person_title}</div>}
      </td>
      <td className="px-4 py-3">
        <div className="text-gray-700 truncate max-w-[140px]">{lead.company_name || '—'}</div>
        {lead.company_domain && <div className="text-xs text-gray-400">{lead.company_domain}</div>}
      </td>
      <td className="px-4 py-3">
        <SourceBadge source={lead.source} />
      </td>
      <td className="px-4 py-3">
        <EmailCell lead={lead} />
      </td>
      <td className="px-4 py-3">
        <ScorePill score={lead.intent_score} />
      </td>
      <td className="px-4 py-3">
        <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', STATUS_COLORS[lead.status] || 'bg-gray-50 text-gray-600')}>
          {lead.status}
        </span>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-1">
          <button onClick={onView} className="p-1.5 text-gray-400 hover:text-primary transition-colors rounded" title="View">
            <Eye className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => onStatusChange('contacted')} className="p-1.5 text-gray-400 hover:text-yellow-500 transition-colors rounded" title="Mark contacted">
            <MessageSquare className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => onStatusChange('qualified', 1)} className="p-1.5 text-gray-400 hover:text-green-500 transition-colors rounded" title="Qualify">
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => onStatusChange('rejected', -1)} className="p-1.5 text-gray-400 hover:text-red-500 transition-colors rounded" title="Reject">
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function EmailCell({ lead }: { lead: Lead }) {
  if (!lead.person_email) {
    return <span className="px-2 py-0.5 bg-gray-100 text-gray-400 text-xs rounded">No email</span>
  }
  return (
    <div className="flex items-center gap-1.5">
      {lead.email_verified
        ? <CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" />
        : <Mail className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
      <span className={clsx('text-xs truncate max-w-[140px]', lead.email_verified ? 'text-gray-800' : 'text-gray-400')}>
        {lead.person_email}
      </span>
    </div>
  )
}

function ScorePill({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.7 ? 'text-green-700' : score >= 0.4 ? 'text-yellow-700' : 'text-gray-500'
  return <span className={clsx('text-sm font-medium tabular-nums', color)}>{pct}%</span>
}

function LeadDrawer({
  lead, outreachText, setOutreachText, onClose, onGenerateOutreach, generatingOutreach,
  onStatusChange, onReEnrich, reEnriching,
}: {
  lead: Lead
  outreachText: string
  setOutreachText: (t: string) => void
  onClose: () => void
  onGenerateOutreach: () => void
  generatingOutreach: boolean
  onStatusChange: (status: string, feedback?: number) => void
  onReEnrich: () => void
  reEnriching: boolean
}) {
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)

  const copyOutreach = () => {
    navigator.clipboard.writeText(outreachText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="w-96 shrink-0 border-l border-gray-200 bg-white overflow-y-auto">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
        <h2 className="font-semibold text-gray-900 text-sm">Lead details</h2>
        <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
      </div>

      <div className="p-5 space-y-5">
        {/* Person */}
        <div>
          <div className="text-lg font-semibold text-gray-900">{lead.person_name}</div>
          {lead.person_title && <div className="text-sm text-gray-500 mt-0.5">{lead.person_title}</div>}
          {lead.person_location && <div className="text-xs text-gray-400 mt-0.5">📍 {lead.person_location}</div>}

          <div className="flex gap-2 mt-2">
            {lead.person_linkedin_url && (
              <a href={lead.person_linkedin_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700">
                <Linkedin className="w-4 h-4" />
              </a>
            )}
            {lead.person_github_url && (
              <a href={lead.person_github_url} target="_blank" rel="noopener noreferrer" className="text-gray-700 hover:text-gray-900">
                <Github className="w-4 h-4" />
              </a>
            )}
            {lead.person_twitter_url && (
              <a href={lead.person_twitter_url} target="_blank" rel="noopener noreferrer" className="text-sky-500 hover:text-sky-600">
                <Twitter className="w-4 h-4" />
              </a>
            )}
          </div>
        </div>

        {/* Email */}
        <div className="p-3 bg-gray-50 rounded-lg">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-gray-500 font-medium">Email</span>
            <button
              onClick={onReEnrich}
              disabled={reEnriching}
              className="text-xs text-primary hover:underline flex items-center gap-1 disabled:opacity-50"
              title="Re-run the enrichment chain (website scrape, GitHub commits, Hunter, patterns)"
            >
              {reEnriching ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              Re-enrich
            </button>
          </div>
          {lead.person_email ? (
            <>
              <div className="flex items-center gap-1.5">
                {lead.email_verified
                  ? <CheckCircle className="w-4 h-4 text-green-500 shrink-0" />
                  : <AlertCircle className="w-4 h-4 text-amber-500 shrink-0" />}
                <span className="text-sm text-gray-900 truncate">{lead.person_email}</span>
              </div>
              {lead.email_source && (() => {
                const meta = EMAIL_SOURCE_LABEL[lead.email_source] || { text: lead.email_source, tone: 'medium' as const }
                const toneCls = meta.tone === 'high'
                  ? 'bg-green-50 text-green-700 border-green-100'
                  : meta.tone === 'medium'
                    ? 'bg-blue-50 text-blue-700 border-blue-100'
                    : 'bg-amber-50 text-amber-700 border-amber-100'
                return (
                  <div className="mt-2 flex items-center gap-2">
                    <span className={clsx('text-xs px-2 py-0.5 rounded border', toneCls)}>
                      {lead.email_verified ? '✓ Verified' : 'Unverified'} · {meta.text}
                    </span>
                  </div>
                )
              })()}
            </>
          ) : (
            <span className="text-sm text-gray-400">Not found — click Re-enrich to try again</span>
          )}
        </div>

        {/* Company */}
        {lead.company_name && (
          <div className="p-3 bg-gray-50 rounded-lg">
            <div className="text-xs text-gray-500 mb-1 font-medium">Company</div>
            <div className="font-medium text-gray-900">{lead.company_name}</div>
            {lead.company_domain && <div className="text-xs text-gray-400 mt-0.5">{lead.company_domain}</div>}
            {lead.company_industry && <div className="text-xs text-gray-400">{lead.company_industry}</div>}
            {lead.company_size && <div className="text-xs text-gray-400">{lead.company_size} employees</div>}
          </div>
        )}

        {/* Score + signals */}
        <div className="p-3 bg-gray-50 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-medium">Intent score</span>
            <span className="font-semibold text-gray-900">{Math.round(lead.intent_score * 100)}%</span>
          </div>
          {lead.intent_signals.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {lead.intent_signals.map((sig) => (
                <span key={sig} className="px-2 py-0.5 bg-primary/10 text-primary text-xs rounded">{sig.replace(/_/g, ' ')}</span>
              ))}
            </div>
          )}
        </div>

        {/* Source */}
        <div className="flex items-center gap-2">
          <SourceBadge source={lead.source} />
          <span className="text-xs text-gray-400">{new Date(lead.created_at).toLocaleDateString()}</span>
        </div>

        {/* Source provenance — where we found them */}
        {(lead.source_url || lead.source_profile_url || lead.source_snippet) && (
          <div className="p-3 bg-gray-50 rounded-lg border border-gray-100 space-y-2">
            <div className="text-xs text-gray-500 font-medium uppercase tracking-wide">Source</div>
            {lead.source_url && (
              <a
                href={lead.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-sm text-primary hover:underline break-all"
              >
                <LinkIcon className="w-3.5 h-3.5 shrink-0" />
                View original post
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
            )}
            {lead.source_profile_url && lead.source_profile_url !== lead.source_url && (
              <a
                href={lead.source_profile_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-sm text-primary hover:underline break-all"
              >
                <UserIcon className="w-3.5 h-3.5 shrink-0" />
                View profile
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
            )}
            {lead.source_snippet && (
              <div className="mt-2 pl-3 border-l-2 border-primary/30 text-xs text-gray-600 italic whitespace-pre-wrap leading-relaxed">
                <Quote className="w-3 h-3 inline-block mr-1 text-primary/50 -mt-1" />
                {lead.source_snippet.slice(0, 600)}
                {lead.source_snippet.length > 600 && '…'}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={() => onStatusChange('contacted')}
            className={clsx('flex-1 btn-secondary text-sm', lead.status === 'contacted' && 'border-yellow-300 text-yellow-700')}
          >
            Mark contacted
          </button>
          <button
            onClick={() => onStatusChange('rejected', -1)}
            className="btn-secondary text-sm px-3 text-red-500 hover:border-red-200"
          >
            Reject
          </button>
        </div>

        {/* Outreach */}
        <div className="border-t border-gray-100 pt-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-700">Outreach email</span>
            <button
              onClick={onGenerateOutreach}
              disabled={generatingOutreach}
              className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"
            >
              {generatingOutreach ? <Loader2 className="w-3 h-3 animate-spin" /> : <MessageSquare className="w-3 h-3" />}
              Generate
            </button>
          </div>
          {outreachText ? (
            <>
              <textarea
                className="input-field resize-none text-xs font-mono"
                rows={8}
                value={outreachText}
                onChange={(e) => setOutreachText(e.target.value)}
              />
              <button
                onClick={copyOutreach}
                className="mt-2 btn-secondary w-full text-sm"
              >
                {copied ? '✓ Copied!' : 'Copy to clipboard'}
              </button>
            </>
          ) : (
            <div className="py-4 text-center text-sm text-gray-400 bg-gray-50 rounded-lg">
              Click Generate to create a personalized email
            </div>
          )}
        </div>

        {/* Raw data */}
        <div className="border-t border-gray-100 pt-4">
          <button
            onClick={() => setShowRaw(!showRaw)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
          >
            <ChevronDown className={clsx('w-3.5 h-3.5 transition-transform', showRaw && 'rotate-180')} />
            Raw data
          </button>
          {showRaw && (
            <pre className="mt-2 p-3 bg-gray-50 rounded text-xs overflow-auto max-h-48 text-gray-600">
              {JSON.stringify(lead.raw_data, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
