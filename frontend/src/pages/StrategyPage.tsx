import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, ChevronRight, Loader2, Zap, CheckCircle, Trash2, ToggleLeft, ToggleRight } from 'lucide-react'
import { strategyApi, type Strategy, type StrategyCreate } from '../api/strategy'
import TagInput from '../components/TagInput'
import clsx from 'clsx'

const SIZE_OPTIONS = ['1-10', '11-50', '51-200', '201-1000', '1000+']

const EMPTY_FORM: StrategyCreate = {
  title: '',
  main_problem: '',
  ideal_customer: '',
  keywords: [],
  buyer_phrases: [],
  target_locations: [],
  target_company_size: [],
  intent_threshold: 0.5,
}

export default function StrategyPage() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Strategy | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<StrategyCreate>(EMPTY_FORM)
  const [icpResult, setIcpResult] = useState<Strategy | null>(null)

  const { data: strategies = [], isLoading } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategyApi.list().then((r) => r.data),
  })

  const createMut = useMutation({
    mutationFn: strategyApi.create,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      setSelected(r.data)
      setIcpResult(r.data)
      setCreating(false)
      // Keep the form populated with the saved data (don't reset)
      setForm({
        title: r.data.title,
        main_problem: r.data.main_problem,
        ideal_customer: r.data.ideal_customer,
        keywords: r.data.keywords,
        buyer_phrases: r.data.buyer_phrases,
        target_locations: r.data.target_locations,
        target_company_size: r.data.target_company_size,
        intent_threshold: r.data.intent_threshold,
      })
    },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: StrategyCreate }) => strategyApi.update(id, data),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      setSelected(r.data)
      setIcpResult(r.data)
    },
  })

  const deleteMut = useMutation({
    mutationFn: strategyApi.delete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      setSelected(null)
      setIcpResult(null)
    },
  })

  const toggleMut = useMutation({
    mutationFn: strategyApi.toggleActive,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const analyzeMut = useMutation({
    mutationFn: strategyApi.analyze,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      setSelected(r.data)
      setIcpResult(r.data)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (creating) {
      createMut.mutate(form)
    } else if (selected) {
      updateMut.mutate({ id: selected.id, data: form })
    }
  }

  const selectStrategy = (s: Strategy) => {
    setSelected(s)
    setCreating(false)
    setIcpResult(s)
    setForm({
      title: s.title,
      main_problem: s.main_problem,
      ideal_customer: s.ideal_customer,
      keywords: s.keywords,
      buyer_phrases: s.buyer_phrases,
      target_locations: s.target_locations,
      target_company_size: s.target_company_size,
      intent_threshold: s.intent_threshold,
    })
  }

  const startCreating = () => {
    setCreating(true)
    setSelected(null)
    setIcpResult(null)
    setForm(EMPTY_FORM)
  }

  const isSaving = createMut.isPending || updateMut.isPending

  return (
    <div className="flex h-full">
      {/* Sidebar list */}
      <div className="w-64 shrink-0 border-r border-gray-200 bg-white flex flex-col">
        <div className="flex items-center justify-between px-4 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900 text-sm">Strategies</h2>
          <button onClick={startCreating} className="w-7 h-7 flex items-center justify-center rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors">
            <Plus className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8"><Loader2 className="w-4 h-4 animate-spin text-gray-400" /></div>
          ) : strategies.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-400">
              No strategies yet.<br />Click + to create one.
            </div>
          ) : (
            strategies.map((s) => (
              <button
                key={s.id}
                onClick={() => selectStrategy(s)}
                className={clsx(
                  'w-full text-left px-4 py-3 flex items-center gap-2 hover:bg-gray-50 transition-colors',
                  selected?.id === s.id && 'bg-primary/5'
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-900 truncate">{s.title}</div>
                  <div className={clsx('text-xs mt-0.5', s.is_active ? 'text-green-600' : 'text-gray-400')}>
                    {s.is_active ? 'Active' : 'Paused'}
                  </div>
                </div>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main panel */}
      <div className="flex-1 overflow-y-auto p-8">
        {!creating && !selected ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center mb-4">
              <Zap className="w-6 h-6 text-gray-400" />
            </div>
            <h3 className="font-semibold text-gray-900 mb-1">No strategy selected</h3>
            <p className="text-sm text-gray-500 mb-4">Create a strategy to start hunting for leads</p>
            <button onClick={startCreating} className="btn-primary flex items-center gap-2">
              <Plus className="w-4 h-4" /> New strategy
            </button>
          </div>
        ) : (
          <div className="max-w-2xl">
            <div className="flex items-center justify-between mb-6">
              <h1 className="text-xl font-semibold text-gray-900">
                {creating ? 'New strategy' : selected?.title}
              </h1>
              {selected && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleMut.mutate(selected.id)}
                    className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
                  >
                    {selected.is_active
                      ? <ToggleRight className="w-5 h-5 text-green-500" />
                      : <ToggleLeft className="w-5 h-5 text-gray-400" />}
                    {selected.is_active ? 'Active' : 'Paused'}
                  </button>
                  <button
                    onClick={() => { if (confirm('Delete this strategy?')) deleteMut.mutate(selected.id) }}
                    className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Strategy name</label>
                <input
                  className="input-field"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="e.g. Fintech CTOs in London"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">What problem do you solve?</label>
                <textarea
                  className="input-field resize-none"
                  rows={3}
                  value={form.main_problem}
                  onChange={(e) => setForm({ ...form, main_problem: e.target.value })}
                  placeholder="We help fintech companies reduce regulatory compliance costs by automating risk reporting..."
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Ideal customer description</label>
                <textarea
                  className="input-field resize-none"
                  rows={3}
                  value={form.ideal_customer}
                  onChange={(e) => setForm({ ...form, ideal_customer: e.target.value })}
                  placeholder="CTO or Head of Risk at a Series A-C fintech with 50-500 employees, building compliance tools..."
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Keywords</label>
                <TagInput value={form.keywords} onChange={(v) => setForm({ ...form, keywords: v })} placeholder="fintech, risk, compliance…" />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Buyer intent phrases</label>
                <TagInput value={form.buyer_phrases} onChange={(v) => setForm({ ...form, buyer_phrases: v })} placeholder="looking for risk tool, compliance automation…" />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Target locations</label>
                <TagInput value={form.target_locations} onChange={(v) => setForm({ ...form, target_locations: v })} placeholder="London, New York, Remote…" />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Target company size</label>
                <div className="flex flex-wrap gap-2">
                  {SIZE_OPTIONS.map((size) => (
                    <button
                      key={size}
                      type="button"
                      onClick={() => {
                        const cur = form.target_company_size
                        setForm({
                          ...form,
                          target_company_size: cur.includes(size)
                            ? cur.filter((s) => s !== size)
                            : [...cur, size],
                        })
                      }}
                      className={clsx(
                        'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors',
                        form.target_company_size.includes(size)
                          ? 'bg-primary text-white border-primary'
                          : 'bg-white text-gray-600 border-gray-200 hover:border-primary/50'
                      )}
                    >
                      {size}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-sm font-medium text-gray-700">Intent threshold</label>
                  <span className="text-sm font-medium text-primary">{form.intent_threshold.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0.3"
                  max="0.9"
                  step="0.05"
                  value={form.intent_threshold}
                  onChange={(e) => setForm({ ...form, intent_threshold: parseFloat(e.target.value) })}
                  className="w-full accent-primary"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>0.3 — more leads</span>
                  <span>0.9 — high quality only</span>
                </div>
              </div>

              {(createMut.isError || updateMut.isError) && (
                <div className="px-3 py-2.5 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600">
                  Save failed. Please try again.
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex items-center gap-2" disabled={isSaving}>
                  {isSaving
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Analyzing with AI…</>
                    : <><Zap className="w-4 h-4" /> {creating ? 'Create & analyze' : 'Save & re-analyze'}</>}
                </button>
                {!creating && selected && (
                  <button
                    type="button"
                    onClick={() => analyzeMut.mutate(selected.id)}
                    disabled={analyzeMut.isPending}
                    className="btn-secondary flex items-center gap-2"
                  >
                    {analyzeMut.isPending
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <Zap className="w-4 h-4" />}
                    Re-analyze
                  </button>
                )}
              </div>
            </form>

            {/* ICP Results */}
            {icpResult && (icpResult.target_roles.length > 0 || icpResult.target_industries.length > 0) && (
              <div className="mt-8 border-t border-gray-100 pt-6">
                <div className="flex items-center gap-2 mb-4">
                  <CheckCircle className="w-4 h-4 text-green-500" />
                  <span className="text-sm font-medium text-gray-700">AI-extracted ICP parameters</span>
                </div>

                <div className="space-y-3">
                  {icpResult.target_roles.length > 0 && (
                    <div>
                      <div className="text-xs text-gray-500 mb-1.5 font-medium uppercase tracking-wide">Target roles</div>
                      <div className="flex flex-wrap gap-1.5">
                        {icpResult.target_roles.map((r) => (
                          <span key={r} className="px-2.5 py-1 bg-blue-50 text-blue-700 text-xs rounded-md font-medium">{r}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {icpResult.target_industries.length > 0 && (
                    <div>
                      <div className="text-xs text-gray-500 mb-1.5 font-medium uppercase tracking-wide">Target industries</div>
                      <div className="flex flex-wrap gap-1.5">
                        {icpResult.target_industries.map((i) => (
                          <span key={i} className="px-2.5 py-1 bg-green-50 text-green-700 text-xs rounded-md font-medium">{i}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {(icpResult.raw_icp_params as { tech_keywords?: string[] })?.tech_keywords?.length ? (
                    <div>
                      <div className="text-xs text-gray-500 mb-1.5 font-medium uppercase tracking-wide">Tech keywords</div>
                      <div className="flex flex-wrap gap-1.5">
                        {((icpResult.raw_icp_params as { tech_keywords?: string[] })?.tech_keywords || []).map((k) => (
                          <span key={k} className="px-2.5 py-1 bg-purple-50 text-purple-700 text-xs rounded-md font-medium">{k}</span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
