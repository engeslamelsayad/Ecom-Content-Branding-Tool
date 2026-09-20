import { useState } from 'react'
import { api } from '../api'
import { Banner } from './ui'

export const IMAGE_MODELS = { sunburst: 'GPT Image 2.5 Sunburst', flare: 'GPT Image 2.5 Flare', nano_banana: 'Nano Banana Pro' }

export default function ProductionConnections({ onSaved, settings }) {
  const [defaults, setDefaults] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const selected = defaults || settings?.defaults
  return <section className="card p-5 space-y-5">
    <h2 className="font-semibold text-white">اتصالات الإنتاج — إعداد المالك</h2>
    <div className="grid lg:grid-cols-3 gap-4">{['openai', 'higgsfield', 'fal'].map(provider => <ProviderConnection key={provider} provider={provider} configured={settings?.connections?.[provider]?.configured} onSaved={onSaved} />)}</div>
    {selected && <div className="space-y-3"><h3 className="text-white text-sm font-semibold">الموديلات الافتراضية</h3>
      <label className="label">الصور<select className="input mt-1" value={selected.image_model} onChange={e => setDefaults({ ...selected, image_model: e.target.value })}>{Object.entries(IMAGE_MODELS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <p className="text-xs text-slate-400">UGC: Seedance 2.5 · لقطات المنتج: Kling 2.6 · التعليق الصوتي: ElevenLabs v3</p>
      <button className="btn-primary" disabled={busy} onClick={async () => { setBusy(true); try { await api.saveProductionDefaults(selected); setMessage('تم حفظ الإعداد الافتراضي.'); await onSaved() } catch (e) { setMessage(e.message) } finally { setBusy(false) } }}>حفظ الافتراضي</button>
      {message && <p className="text-sm text-slate-300">{message}</p>}
    </div>}
  </section>
}

function ProviderConnection({ provider, configured, onSaved }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const info = { openai: ['OpenAI', 'Sunburst / Flare والكابشن', 'https://platform.openai.com/api-keys'],
    higgsfield: ['Higgsfield', 'UGC بمقدم عبر Seedance 2.5', 'https://console.higgsfield.ai'],
    fal: ['fal', 'Nano Banana وKling والتعليق الصوتي', 'https://fal.ai/dashboard/keys'] }[provider]
  async function act(fn) { setBusy(true); setError(''); setMessage(''); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <div className="rounded-xl border border-ink-line p-4 space-y-3">
    <h3 className="text-white font-semibold">{info[0]} <span className="chip">{configured ? 'مفتاح محفوظ' : 'غير متصل'}</span></h3>
    <p className="text-xs text-slate-400">{info[1]}. المفتاح يُحفظ مشفرًا ولا يرجع للمتصفح.</p>
    <a className="text-xs text-brand-300 underline" href={info[2]} target="_blank" rel="noreferrer">فتح حساب {info[0]}</a>
    <input className="input" aria-label={`مفتاح ${provider} API`} type="password" autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)} placeholder={provider === 'higgsfield' ? 'KEY_ID:KEY_SECRET' : 'API key'} />
    <div className="flex flex-wrap gap-2"><button className="btn-primary" disabled={busy || !key.trim()} onClick={() => act(async () => { await api.saveConnection(key, provider); setKey(''); setMessage('تم الحفظ مشفرًا.'); await onSaved() })}>حفظ</button><button className="btn-ghost" disabled={busy || !configured} onClick={() => act(async () => setMessage((await api.checkConnection(provider)).message))}>فحص بدون توليد</button></div>
    {message && <Banner kind="success">{message}</Banner>}{error && <Banner kind="error">{error}</Banner>}
  </div>
}
