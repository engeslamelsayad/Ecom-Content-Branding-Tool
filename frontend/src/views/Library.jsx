import { useState } from 'react'
import { Download, FileText, Trash2 } from 'lucide-react'
import { api } from '../api'
import { Banner, Markdown, Modal, Spinner, money, useAsync } from '../components/ui'

const STATUS = {
  done: ['تم', 'text-emerald-300 border-emerald-500/40'],
  running: ['بيشتغل', 'text-amber-300 border-amber-500/40'],
  queued: ['في الطابور', 'text-slate-400 border-ink-line'],
  error: ['خطأ', 'text-rose-300 border-rose-500/40'],
}

/** Every output the tool ever produced for this brand, searchable and versioned. */
export default function Library({ brand, modules }) {
  const runs = useAsync(() => api.runs(`?brand_id=${brand.id}&limit=100`), [brand.id])
  const [open, setOpen] = useState(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  const titleOf = (key) => modules.find((m) => m.key === key)?.title || key

  const items = (runs.data?.items || []).filter((r) => {
    const haystack = `${titleOf(r.module_key)} ${r.preview}`.toLowerCase()
    return haystack.includes(query.toLowerCase())
  })

  async function remove(id) {
    if (!confirm('مسح المخرج ده نهائيًا؟')) return
    try { await api.deleteRun(id); runs.reload() } catch (err) { setError(err.message) }
  }

  return (
    <div className="space-y-4">
      {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}

      <div className="flex flex-wrap items-center gap-3">
        <input className="input flex-1 min-w-[200px]" placeholder="ابحث في المخرجات…"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="chip">{items.length} من {runs.data?.total ?? 0}</span>
      </div>

      {runs.loading ? <div className="p-10 grid place-items-center"><Spinner className="w-6 h-6" /></div> : (
        <div className="space-y-2">
          {items.map((r) => {
            const [label, tone] = STATUS[r.status] || STATUS.queued
            return (
              <article key={r.id}
                       className="card p-4 flex flex-wrap items-center gap-3 hover:border-brand-500/30
                                  transition cursor-pointer"
                       onClick={() => setOpen(r.id)}>
                <FileText className="w-4 h-4 text-slate-600 shrink-0" />
                <div className="flex-1 min-w-[200px]">
                  <div className="text-sm text-white flex items-center gap-2 flex-wrap">
                    {titleOf(r.module_key)}
                    {r.section_key && <span className="chip">{r.section_key}</span>}
                  </div>
                  <div className="text-xs text-slate-600 line-clamp-1 mt-0.5">
                    {r.preview || '—'}
                  </div>
                </div>

                {r.scores?.total != null && (
                  <span className="chip !text-brand-200 !border-brand-500/40">
                    {r.scores.total}/100
                  </span>
                )}
                <span className={`chip ${tone}`}>{label}</span>
                <span className="text-[11px] text-slate-600 tabular-nums">{money(r.cost_usd)}</span>
                <span className="text-[11px] text-slate-600">
                  {new Date(r.created_at).toLocaleDateString('ar-EG')}
                </span>

                <button onClick={(e) => { e.stopPropagation(); remove(r.id) }}
                        className="text-slate-700 hover:text-rose-400">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </article>
            )
          })}
          {!items.length && (
            <p className="text-sm text-slate-600 py-10 text-center">
              مفيش مخرجات {query ? 'مطابقة للبحث' : 'لسه — شغّل موديول من التابات فوق'}.
            </p>
          )}
        </div>
      )}

      <RunModal runId={open} onClose={() => setOpen(null)} />
    </div>
  )
}

function RunModal({ runId, onClose }) {
  const run = useAsync(() => (runId ? api.run(runId) : Promise.resolve(null)), [runId])
  if (!runId) return null

  return (
    <Modal open wide title={run.data?.title || 'جارٍ التحميل…'} onClose={onClose}>
      {run.loading ? <Spinner /> : run.error ? <Banner kind="error">{run.error}</Banner> : (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {['docx', 'pdf', 'md'].map((fmt) => (
              <a key={fmt} href={api.exportUrl(runId, fmt)} className="btn-ghost !py-1.5 !px-3 text-xs">
                <Download className="w-3.5 h-3.5" /> {fmt.toUpperCase()}
              </a>
            ))}
            <span className="chip ms-auto">{run.data.model}</span>
            <span className="chip">{money(run.data.cost_usd)}</span>
          </div>

          {run.data.error && <Banner kind="error">{run.data.error}</Banner>}

          <div className="max-h-[60vh] overflow-y-auto rounded-xl border border-ink-line
                          bg-ink px-4 py-3">
            <Markdown text={run.data.output_md} />
          </div>
        </div>
      )}
    </Modal>
  )
}
