import { useEffect, useState } from 'react'
import { FileText, Trash2 } from 'lucide-react'
import { api } from '../api'
import { Banner, Modal, Spinner, money, useAsync } from '../components/ui'
import OutputWorkbench from '../components/OutputWorkbench'

const STATUS = { done: 'تم', running: 'بيشتغل', queued: 'في الطابور', error: 'خطأ', interrupted: 'متوقف — قابل للاستكمال' }

export default function Library({ brand, modules, onStudio, onChanged }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [filter, setFilter] = useState('')
  const [open, setOpen] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { const t = setTimeout(() => { setSearch(query); setPage(0) }, 300); return () => clearTimeout(t) }, [query])
  const runs = useAsync(() => api.runs(`?brand_id=${brand.id}&limit=20&offset=${page * 20}&q=${encodeURIComponent(search)}&module_key=${filter}`), [brand.id, search, page, filter])
  useEffect(() => {
    if (!runs.data?.items.some(r => ['running', 'queued'].includes(r.status))) return
    const t = setTimeout(runs.reload, 4000)
    return () => clearTimeout(t)
  }, [runs.data])
  async function remove(id) {
    if (!confirm('مسح المخرج نهائيًا؟')) return
    try { await api.deleteRun(id); runs.reload() } catch (e) { setError(e.message) }
  }
  return <div className="space-y-4">
    {(error || runs.error) && <Banner kind="error">{error || runs.error}</Banner>}
    <div className="flex flex-wrap gap-3">
      <input aria-label="بحث في المكتبة" className="input flex-1 min-w-[180px]" placeholder="بحث في النص الكامل للمخرجات…" value={query} onChange={e => setQuery(e.target.value)} />
      <select aria-label="فلتر الموديول" className="input !w-auto" value={filter} onChange={e => { setFilter(e.target.value); setPage(0) }}><option value="">كل الموديولات</option>{modules.filter(m => m.kind !== 'calculator').map(m => <option key={m.key} value={m.key}>{m.title}</option>)}</select>
      <span className="chip">{runs.data?.total || 0} مخرج</span>
    </div>
    {runs.loading ? <Spinner /> : <div className="space-y-2">{(runs.data?.items || []).map(r => <article key={r.id} className="card p-4 flex flex-wrap items-center gap-3">
      <button className="flex-1 text-start min-w-[160px]" onClick={() => setOpen(r)}>
        <span className="flex gap-2 text-white text-sm"><FileText className="w-4 h-4" />{r.title || r.module_key}</span>
        <p className="text-xs text-slate-500 line-clamp-1 mt-1">{r.preview || 'المخرجات ستظهر هنا'}</p>
      </button>
      <span className="chip">{STATUS[r.status] || r.status}</span><span className="chip">{r.workflow === 'approved' ? 'معتمد' : 'مسودة / مراجعة'}</span>
      <span className="text-xs text-slate-500">{money(r.cost_usd)}</span>
      {['error', 'interrupted'].includes(r.status) && brand.role !== 'viewer' && <button className="btn-ghost !py-1" onClick={async () => { try { await api.resumeRun(r.id); runs.reload() } catch (e) { setError(e.message) } }}>استكمال (قد يُحسب القسم غير المكتمل مجددًا)</button>}
      {!['running', 'queued'].includes(r.status) && brand.role !== 'viewer' && <button aria-label="حذف المخرج" onClick={() => remove(r.id)}><Trash2 className="w-4 h-4 text-slate-500" /></button>}
    </article>)}</div>}
    {!runs.loading && !runs.data?.items.length && <p className="text-slate-500">لا توجد مخرجات مطابقة.</p>}
    <div className="flex items-center gap-3"><button className="btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>السابق</button><span className="text-sm text-slate-500">صفحة {page + 1}</span><button className="btn-ghost" disabled={(page + 1) * 20 >= (runs.data?.total || 0)} onClick={() => setPage(page + 1)}>التالي</button></div>
    <Modal open={!!open} wide title={open?.title || 'المخرج'} onClose={() => setOpen(null)}>
      {open && <OutputWorkbench key={open.id} runId={open.id} brand={brand} onStudio={onStudio} onChanged={() => { runs.reload(); onChanged?.() }} />}
    </Modal>
  </div>
}
