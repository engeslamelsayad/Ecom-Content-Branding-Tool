import { useEffect, useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { AlertTriangle, CheckCircle2, Loader2, Lock, Sparkles, Undo2, X } from 'lucide-react'

marked.setOptions({ gfm: true, breaks: true })

/** Renders generated Markdown. Sanitised, since the model's output is HTML-adjacent. */
export function Markdown({ text }) {
  const html = useMemo(() => {
    if (!text) return ''
    const stripped = text.replace(/<!--section:[^>]*-->/g, '')
    return DOMPurify.sanitize(marked.parse(stripped))
  }, [text])

  useEffect(() => {
    // Tables overflow on phones; give each one its own scroll container.
    document.querySelectorAll('.prose-out table').forEach((table) => {
      if (!table.parentElement?.classList.contains('table-wrap')) {
        const wrap = document.createElement('div')
        wrap.className = 'table-wrap'
        table.parentNode.insertBefore(wrap, table)
        wrap.appendChild(table)
      }
    })
  }, [html])

  return <div className="prose-out" dangerouslySetInnerHTML={{ __html: html }} />
}

export function Spinner({ className = 'w-4 h-4' }) {
  return <Loader2 className={`${className} animate-spin`} />
}

export function Banner({ kind = 'info', children, onClose }) {
  const tone = {
    error: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    warn: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    info: 'border-brand-500/40 bg-brand-500/10 text-brand-100',
  }[kind]
  const Icon = kind === 'success' ? CheckCircle2 : AlertTriangle

  return (
    <div className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm ${tone}`}>
      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">{children}</div>
      {onClose && (
        <button onClick={onClose} className="opacity-60 hover:opacity-100 shrink-0">
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}

export function Modal({ open, title, onClose, children, wide }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                    bg-black/70 backdrop-blur-sm p-4 sm:p-6">
      <div className={`card w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} my-8 animate-rise`}>
        <div className="flex items-center justify-between border-b border-ink-line px-5 py-3.5">
          <h3 className="font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

const CONFIDENCE = {
  high: ['موثوق', 'text-emerald-300 border-emerald-500/40'],
  medium: ['مبدئي', 'text-brand-200 border-brand-500/40'],
  low: ['غير مؤكد', 'text-amber-300 border-amber-500/40'],
}

/**
 * One form control, driven by the field descriptor the catalogue returns.
 *
 * `suggestion` is a proposal from the assistant. A proposed value lands in the
 * input so it can be edited in place, with its source shown underneath and one
 * click to revert — never a silent fill. A field the assistant is not allowed
 * to answer says so instead.
 */
export function FormField({ field, value, onChange, suggestion, busy, onAssist, onRevert }) {
  const common = {
    id: field.name,
    value: value ?? '',
    placeholder: field.placeholder,
    onChange: (e) => onChange(field.name, e.target.value),
    className: `input ${suggestion && !suggestion.needs_user ? 'border-brand-500/60 bg-brand-500/[.04]' : ''}`,
  }

  const canAssist = field.assist !== 'none' && field.type !== 'file'

  return (
    <div>
      <label className="label flex items-center gap-1.5" htmlFor={field.name}>
        <span>
          {field.label}
          {field.required && <span className="text-rose-400 ms-1">*</span>}
        </span>

        {canAssist ? (
          <button type="button" onClick={() => onAssist?.(field.name)} disabled={busy}
                  title="اقترح قيمة"
                  className="ms-auto text-slate-600 hover:text-brand-300 transition disabled:opacity-40">
            {busy ? <Spinner className="w-3.5 h-3.5" /> : <Sparkles className="w-3.5 h-3.5" />}
          </button>
        ) : (
          <span className="ms-auto inline-flex items-center gap-1 text-[10px] text-slate-600"
                title="بيانات انت بس اللي عندك — الأداة مش هتخترعها">
            <Lock className="w-3 h-3" /> بياناتك
          </span>
        )}
      </label>

      {field.type === 'textarea' ? (
        <textarea {...common} rows={3} className="input resize-y min-h-[76px]" />
      ) : field.type === 'select' ? (
        <select {...common}>
          <option value="">— اختَر —</option>
          {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : field.type === 'number' ? (
        <input {...common} type="number" step="any" />
      ) : field.type === 'file' ? (
        <input
          type="file"
          accept={field.name === 'video' ? 'video/*' : 'image/*'}
          onChange={(e) => onChange(field.name, e.target.files?.[0] ?? null)}
          className="input file:me-3 file:rounded-lg file:border-0 file:bg-brand-500
                     file:px-3 file:py-1.5 file:text-white file:text-xs file:cursor-pointer"
        />
      ) : (
        <input {...common} type={field.type === 'url' ? 'url' : 'text'} />
      )}

      {field.help && <p className="mt-1 text-[11px] text-slate-500">{field.help}</p>}

      {suggestion && (
        suggestion.needs_user ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-300/90">
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
            <span>{suggestion.basis}</span>
          </p>
        ) : (
          <div className="mt-1.5 flex items-start gap-1.5 text-[11px]">
            <span className={`chip !py-0.5 !text-[10px] ${CONFIDENCE[suggestion.confidence]?.[1] || ''}`}>
              {CONFIDENCE[suggestion.confidence]?.[0] || suggestion.confidence}
            </span>
            <span className="flex-1 text-slate-500">{suggestion.basis}</span>
            <button type="button" onClick={() => onRevert?.(field.name)}
                    title="ارجع للقيمة اللي كانت"
                    className="text-slate-600 hover:text-slate-300 shrink-0">
              <Undo2 className="w-3 h-3" />
            </button>
          </div>
        )
      )}
    </div>
  )
}

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    fn()
      .then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((error) => alive && setState({ loading: false, data: null, error: error.message }))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { ...state, reload: () => setNonce((n) => n + 1) }
}

export const money = (n) => (n == null ? '—' : `$${Number(n).toFixed(n < 1 ? 4 : 2)}`)
export const num = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'))
