import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowRight, Brain, Download, FileText, Play, RefreshCw, Sparkles, Square, Wand2,
} from 'lucide-react'
import { api, streamRun } from '../api'
import { Banner, FormField, Markdown, Spinner, money } from '../components/ui'
import OutputWorkbench from '../components/OutputWorkbench'

const EMPTY = { text: '', thinking: '', status: '', usage: null, error: '', section: null }

export default function ModuleRun({ module, brand, onBack, onBrainChanged, onStudio, initialInputs, draftScope }) {
  const draftKey = `ecbt.draft.${draftScope}.${brand.id}.${module.key}`
  const [inputs, setInputs] = useState(() => {
    let stored = {}
    try { stored = JSON.parse(sessionStorage.getItem(draftKey) || '{}') } catch { /* invalid draft */ }
    const allowed = new Set(module.fields.map(f => f.name))
    return Object.fromEntries(Object.entries({ ...stored, ...initialInputs }).filter(([key]) => allowed.has(key)))
  })
  const [model, setModel] = useState('')
  const [runId, setRunId] = useState(null)
  const [live, setLive] = useState(EMPTY)
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState('')
  const [showThinking, setShowThinking] = useState(false)
  const [suggestions, setSuggestions] = useState({})
  const [assisting, setAssisting] = useState(null)   // field name, or '*' for the whole form
  const [assistCost, setAssistCost] = useState(0)

  const priorRef = useRef({})   // values replaced by a suggestion, for revert

  const cancelRef = useRef(null)
  const activeRunRef = useRef(null)
  const outputRef = useRef(null)
  const pinnedRef = useRef(true)
  const sendingRef = useRef(false)
  useEffect(() => {
    try { sessionStorage.setItem(draftKey, JSON.stringify(Object.fromEntries(Object.entries(inputs).filter(([, v]) => !(v instanceof File))))) } catch { /* storage unavailable */ }
  }, [inputs, draftKey])

  const setField = (name, value) => {
    setInputs((prev) => ({ ...prev, [name]: value }))
    // Once the operator edits it, it is their value — drop the AI marking.
    setSuggestions((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev))
  }

  async function askAssist(only) {
    const target = only || '*'
    setAssisting(target); setError('')
    try {
      const body = { brand_id: brand.id, module_key: module.key, inputs: inputs }
      if (only) body.fields = [only]

      const res = await api.assistFields(body)
      const next = { ...suggestions }
      const values = { ...inputs }

      for (const s of res.suggestions) {
        next[s.field] = s
        if (!s.needs_user && s.value) {
          priorRef.current[s.field] = values[s.field] ?? ''
          values[s.field] = s.value
        }
      }
      setSuggestions(next)
      setInputs(values)
      setAssistCost((c) => c + (res.cost_usd || 0))
    } catch (err) {
      setError(err.message)
    } finally {
      setAssisting(null)
    }
  }

  function revert(name) {
    setInputs((prev) => ({ ...prev, [name]: priorRef.current[name] ?? '' }))
    setSuggestions((prev) => ({ ...prev, [name]: undefined }))
  }

  // Follow the output while the user has not scrolled away from the bottom.
  useEffect(() => {
    const el = outputRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [live.text])

  const onScroll = () => {
    const el = outputRef.current
    if (!el) return
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const attach = useCallback((id, parentId = null) => {
    activeRunRef.current = id
    setRunning(true)
    cancelRef.current?.()
    cancelRef.current = streamRun(id, (event) => {
      switch (event.type) {
        case 'text':
          setLive((s) => ({ ...s, text: s.text + event.text })); break
        case 'thinking':
          setLive((s) => ({ ...s, thinking: s.thinking + event.text })); break
        case 'status':
          setLive((s) => ({ ...s, status: event.text })); break
        case 'section':
          setLive((s) => ({ ...s, status: '', section: event })); break
        case 'usage':
          setLive((s) => ({ ...s, usage: event })); break
        case 'error':
          setLive((s) => ({ ...s, error: event.text })); setRunning(false); break
        case 'done':
          setLive((s) => ({ ...s, status: '', section: null })); setRunning(false)
          setFinished(true)
          if (parentId) api.run(parentId).then(r => setLive(s => ({ ...s, text: r.output_md })))
          onBrainChanged?.(); break
        case 'end':
          setRunning(false); break
        default: break
      }
    })
  }, [onBrainChanged])

  useEffect(() => () => cancelRef.current?.(), [])

  async function start() {
    if (sendingRef.current) return
    sendingRef.current = true
    activeRunRef.current = null
    setRunning(true); setFinished(false)
    setError(''); setLive(EMPTY)
    try {
      const payload = { ...inputs }

      // Files are uploaded first; the run then references them by id, never by path.
      for (const [field, key, kind] of [['image', 'image_asset_id', 'image'],
                                        ['video', 'video_asset_id', 'video']]) {
        if (payload[field] instanceof File) {
          setLive((s) => ({ ...s, status: 'برفع الملف…' }))
          const asset = await api.uploadAsset(brand.id, payload[field], kind)
          payload[key] = asset.id
        }
        delete payload[field]
      }

      const run = await api.createRun({
        brand_id: brand.id, module_key: module.key, inputs: payload, model: model || null,
      })
      setRunId(run.id)
      attach(run.id)
    } catch (err) {
      setError(err.message); setRunning(false)
      setLive((s) => ({ ...s, status: '' }))
    } finally { sendingRef.current = false }
  }

  async function regenerate(sectionKey) {
    try {
      const child = await api.regenSection(runId, sectionKey, model || undefined)
      setFinished(false); setLive(EMPTY)
      attach(child.id, runId)
    } catch (err) { setError(err.message) }
  }

  async function stop() {
    if (sendingRef.current) { setError('انتظر اكتمال رفع الملف وإرسال الطلب، ثم اضغط إيقاف.'); return }
    try { if (activeRunRef.current) await api.cancelRun(activeRunRef.current); cancelRef.current?.(); setRunning(false) }
    catch (err) { setError(err.message) }
  }

  const hasOutput = Boolean(live.text.trim())

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="btn-ghost !px-2.5 !py-2">
          <ArrowRight className="w-4 h-4" />
        </button>
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-white truncate">{module.title}</h1>
          <p className="text-xs text-slate-500 truncate">{module.subtitle}</p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)] items-start">
        {/* ---- Inputs ---- */}
        <aside className="card p-5 space-y-4 lg:sticky lg:top-4">
          {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}

          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            {module.skill && <span className="chip">{module.skill}</span>}
            {module.command && <span className="chip font-mono">{module.command}</span>}
            <span className="chip">{module.tier === 'fast' ? 'سريع' : 'عميق'}</span>
          </div>

          {module.fields.some((f) => f.assist !== 'none' && f.type !== 'file') && (
            <button type="button" onClick={() => askAssist(null)} disabled={assisting !== null}
                    className="btn-ghost w-full !py-2 text-xs border-dashed
                               hover:border-brand-500/50 hover:text-brand-200">
              {assisting === '*' ? <Spinner className="w-3.5 h-3.5" /> : <Wand2 className="w-3.5 h-3.5" />}
              املا الفاضي بالـ AI
            </button>
          )}

          {module.fields.map((f) => (
            <FormField key={f.name} field={f.name === 'product' ? { ...f, type: brand.products.length ? 'select' : 'text', options: brand.products.map(p => p.name) } : f} value={inputs[f.name]} onChange={setField}
                       suggestion={suggestions[f.name]}
                       busy={assisting === f.name || assisting === '*'}
                       onAssist={askAssist} onRevert={revert} />
          ))}

          {assistCost > 0 && (
            <p className="flex items-center gap-1.5 text-[11px] text-slate-600">
              <Sparkles className="w-3 h-3" />
              المساعدة كلّفت {money(assistCost)} — راجع الاقتراحات قبل ما تشغّل.
            </p>
          )}

          <div>
            <label className="label">الموديل</label>
            <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">تلقائي ({module.tier === 'fast' ? 'Sonnet' : 'Opus'})</option>
              <option value="claude-opus-5">Opus 5 — أعمق</option>
              <option value="claude-sonnet-5">Sonnet 5 — أسرع وأرخص</option>
            </select>
          </div>

          {running ? (
            <button className="btn-ghost w-full" onClick={stop}>
              <Square className="w-4 h-4" /> إيقاف التوليد
            </button>
          ) : (
            <button className="btn-primary w-full" onClick={start} disabled={brand.role === 'viewer'}>
              <Play className="w-4 h-4" /> {hasOutput ? 'شغّل من جديد' : 'شغّل الموديول'}
            </button>
          )}

          {live.usage && (
            <div className="rounded-xl border border-ink-line bg-ink p-3 text-[11px] space-y-1">
              <Row label="توكنز داخلة" value={live.usage.input?.toLocaleString()} />
              <Row label="من الكاش" value={live.usage.cache_read?.toLocaleString()} accent />
              <Row label="توكنز خارجة" value={live.usage.output?.toLocaleString()} />
              <div className="border-t border-ink-line pt-1 mt-1">
                <Row label="التكلفة" value={money(live.usage.cost)} strong />
              </div>
            </div>
          )}

          {runId && hasOutput && !running && (
            <div className="flex flex-wrap gap-2 pt-1">
              {['docx', 'pdf', 'md'].map((fmt) => (
                <a key={fmt} href={api.exportUrl(runId, fmt)}
                   className="btn-ghost !py-1.5 !px-2.5 text-xs flex-1">
                  <Download className="w-3.5 h-3.5" /> {fmt.toUpperCase()}
                </a>
              ))}
            </div>
          )}
        </aside>

        {/* ---- Output ---- */}
        <section className="card min-h-[460px] flex flex-col">
          <header className="flex flex-wrap items-center gap-2 border-b border-ink-line px-5 py-3">
            <FileText className="w-4 h-4 text-slate-600" />
            <span className="text-sm text-slate-400 flex-1">المخرجات</span>

            {live.section && (
              <span className="chip !text-brand-200 !border-brand-500/40">
                {live.section.index}/{live.section.total} — {live.section.title}
              </span>
            )}
            {live.status && (
              <span className="chip !text-amber-200 !border-amber-500/40">
                <Spinner className="w-3 h-3" /> {live.status}
              </span>
            )}
            {live.thinking && (
              <button className="chip hover:text-brand-200"
                      onClick={() => setShowThinking((v) => !v)}>
                <Brain className="w-3 h-3" /> التفكير
              </button>
            )}
          </header>

          {showThinking && live.thinking && (
            <div className="border-b border-ink-line bg-ink/60 px-5 py-3 max-h-48 overflow-y-auto
                            text-xs text-slate-500 whitespace-pre-wrap leading-relaxed">
              {live.thinking}
            </div>
          )}

          <div ref={outputRef} onScroll={onScroll}
               className="flex-1 overflow-y-auto px-5 py-4 max-h-[calc(100vh-230px)]">
            {live.error && <Banner kind="error">{live.error}</Banner>}

            {!hasOutput && !live.error && (
              <div className="h-full grid place-items-center text-center py-16">
                {running ? (
                  <div className="space-y-3">
                    <Spinner className="w-6 h-6 mx-auto text-brand-400" />
                    <p className="text-sm text-slate-500">
                      {live.status || 'بيشتغل… المخرجات هتظهر وهي بتتكتب'}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2 max-w-xs">
                    <p className="text-sm text-slate-500">املا الحقول على الشمال واضغط تشغيل.</p>
                    <p className="text-[11px] text-slate-600">
                      الموديول بياخد سياق البراند كله تلقائي — مش هيسألك من الأول.
                    </p>
                  </div>
                )}
              </div>
            )}

            {finished && runId ? <OutputWorkbench key={`${runId}:${live.text.length}`} runId={runId} brand={brand} onStudio={onStudio} onChanged={onBrainChanged} /> : hasOutput && <Markdown text={live.text} />}
            {running && hasOutput && (
              <span className="inline-block w-2 h-4 bg-brand-400 align-middle animate-pulseDot" />
            )}
          </div>

          {module.sections?.length > 0 && hasOutput && !running && (
            <footer className="border-t border-ink-line px-5 py-3">
              <p className="text-[11px] text-slate-500 mb-2">
                إعادة توليد قسم واحد بس — من غير ما تعيد الخطة كلها:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {module.sections.map((s) => (
                  <button key={s.key} onClick={() => regenerate(s.key)}
                          className="chip hover:text-brand-200 hover:border-brand-500/40">
                    <RefreshCw className="w-3 h-3" /> {s.title.replace(/^Module \d+ — /, '')}
                  </button>
                ))}
              </div>
            </footer>
          )}
        </section>
      </div>
    </div>
  )
}

function Row({ label, value, accent, strong }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500">{label}</span>
      <span className={strong ? 'text-white font-semibold'
                      : accent ? 'text-emerald-400' : 'text-slate-300'}>{value ?? '—'}</span>
    </div>
  )
}
