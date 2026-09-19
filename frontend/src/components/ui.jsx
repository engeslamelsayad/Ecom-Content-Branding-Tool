import { useEffect, useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-react'

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

/** One form control, driven by the field descriptor the catalogue returns. */
export function FormField({ field, value, onChange }) {
  const common = {
    id: field.name,
    value: value ?? '',
    placeholder: field.placeholder,
    onChange: (e) => onChange(field.name, e.target.value),
    className: 'input',
  }

  return (
    <div>
      <label className="label" htmlFor={field.name}>
        {field.label}
        {field.required && <span className="text-rose-400 ms-1">*</span>}
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
