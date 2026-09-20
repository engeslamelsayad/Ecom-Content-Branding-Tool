import { useEffect, useState } from 'react'
import { Copy, Download, Pencil, Save, Sparkles } from 'lucide-react'
import { api } from '../api'
import { Banner, Markdown, Spinner } from './ui'

const LABELS = { draft: 'مسودة', internal_review: 'مراجعة داخلية', client_review: 'مراجعة العميل', approved: 'معتمد' }

export default function OutputWorkbench({ runId, brand, onStudio, onChanged }) {
  const [run, setRun] = useState(null)
  const [flow, setFlow] = useState(null)
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(false)
  const [revision, setRevision] = useState('')
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const canEdit = brand.role !== 'viewer'
  async function load() {
    const [r, f] = await Promise.all([api.run(runId), api.workflow(runId)])
    setRun(r); setFlow(f); setText(r.output_md)
  }
  useEffect(() => { let alive = true; Promise.all([api.run(runId), api.workflow(runId)]).then(([r, f]) => {
    if (alive) { setRun(r); setFlow(f); setText(r.output_md) }
  }).catch(e => alive && setError(e.message)); return () => { alive = false } }, [runId])
  async function act(fn) { setBusy(true); setError(''); setNotice(''); try { await fn(); await load(); onChanged?.() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  if (!run || !flow) return error ? <Banner kind="error">{error}</Banner> : <Spinner />
  const old = flow.revisions.find(r => r.id === revision)
  return <div className="space-y-4">
    {error && <Banner kind="error">{error}</Banner>}{notice && <Banner kind="success">{notice}</Banner>}
    <div className="flex flex-wrap gap-2 items-center">
      <span className="chip">{LABELS[flow.status]} · نسخة {flow.version}</span>
      {canEdit && <button className="btn-ghost" disabled={busy} onClick={() => setEditing(!editing)}><Pencil className="w-4 h-4" />{editing ? 'معاينة' : 'تعديل'}</button>}
      <button className="btn-ghost" onClick={async () => { try { await navigator.clipboard.writeText(editing ? text : run.output_md); setNotice('تم نسخ النص.') } catch { setError('تعذّر النسخ. حدّد النص وانسخه يدويًا.') } }}><Copy className="w-4 h-4" />نسخ</button>
      {['docx', 'pdf', 'md'].map(fmt => <a key={fmt} className="btn-ghost !px-2 text-xs" href={api.exportUrl(run.id, fmt)}><Download className="w-3 h-3" />{fmt.toUpperCase()}</a>)}
    </div>
    {editing ? <><textarea aria-label="تحرير المخرج" className="input min-h-[350px]" value={text} onChange={e => setText(e.target.value)} />
      <button className="btn-primary" disabled={busy || !text.trim()} onClick={() => act(async () => { await api.editOutput(run.id, { output_md: text, version: flow.version }); setEditing(false) })}><Save className="w-4 h-4" />حفظ نسخة جديدة</button></>
      : <div className="max-h-[65vh] overflow-auto"><Markdown text={run.output_md} /></div>}
    <div className="flex flex-wrap gap-2 border-t border-ink-line pt-3">
      {canEdit && Object.entries(LABELS).filter(([id]) => id !== 'approved' || brand.role === 'admin').map(([id, label]) => <button className="chip" key={id} disabled={busy || editing || run.status !== 'done'} onClick={() => act(() => api.setWorkflow(run.id, { status: id, version: flow.version }))}>{label}</button>)}
    </div>
    {flow.writes_core && <p className="text-xs text-slate-500">اعتماد المخرج بواسطة مسؤول العميل يحدّث «{flow.writes_core}» في Brand Brain. التعديل اللاحق يظل مسودة حتى اعتماده.</p>}
    {canEdit && onStudio && <div className="rounded-xl border border-brand-500/30 p-3 space-y-2"><p className="text-sm text-white flex gap-2"><Sparkles className="w-4 h-4" />حوّل لإنتاج</p>
      <div className="flex flex-wrap gap-2">{[['image', 'تصميم'], ['audio', 'صوت'], ['video', 'فيديو']].map(([kind, label]) => <button key={kind} className="btn-ghost" disabled={editing} onClick={() => onStudio({ kind, text: run.output_md, runId: run.id })}>{label}</button>)}</div>
      <p className="text-xs text-slate-500">هتراجع وصف المشاهد والنص المنطوق قبل إرسال أي طلب مدفوع.</p></div>}
    {flow.revisions.length > 0 && <details><summary className="text-sm cursor-pointer text-slate-300">مقارنة النسخ والرجوع</summary>
      <select className="input my-2" value={revision} onChange={e => setRevision(e.target.value)}><option value="">اختر نسخة سابقة</option>{flow.revisions.map(r => <option key={r.id} value={r.id}>{r.note} — {new Date(r.created_at).toLocaleString('ar-EG')}</option>)}</select>
      {old && <><div className="grid md:grid-cols-2 gap-3"><div className="border border-ink-line rounded-lg p-3 max-h-64 overflow-auto"><p className="text-xs text-slate-500">السابقة</p><Markdown text={old.output_md} /></div><div className="border border-ink-line rounded-lg p-3 max-h-64 overflow-auto"><p className="text-xs text-slate-500">الحالية</p><Markdown text={run.output_md} /></div></div>
        {canEdit && <button className="btn-ghost mt-2" disabled={busy} onClick={() => act(() => api.editOutput(run.id, { output_md: old.output_md, version: flow.version }))}>استعادة السابقة كمسودة جديدة</button>}</>}
    </details>}
    <div className="space-y-2 border-t border-ink-line pt-3"><p className="text-sm text-white">تعليقات المراجعة</p>
      {flow.comments.map((c, i) => <div key={i} className="rounded-lg bg-ink p-3 text-sm"><span className="text-brand-300">{c.author}</span><p className="text-slate-300 whitespace-pre-wrap">{c.text}</p></div>)}
      <textarea className="input" rows={2} aria-label="تعليق المراجعة" value={comment} onChange={e => setComment(e.target.value)} placeholder="اكتب ملاحظتك…" />
      <button className="btn-ghost" disabled={busy || !comment.trim()} onClick={() => act(async () => { await api.comment(run.id, comment); setComment('') })}>إضافة تعليق</button>
    </div>
  </div>
}
