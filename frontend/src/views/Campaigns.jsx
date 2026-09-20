import { useState } from 'react'
import { api } from '../api'
import { Banner, Spinner, useAsync } from '../components/ui'

export default function Campaigns({ brand, onModule, onStudio }) {
  const rows = useAsync(() => api.campaigns(brand.id), [brand.id])
  const [campaign, setCampaign] = useState(null)
  const [title, setTitle] = useState('')
  const [brief, setBrief] = useState({ product: '', audience: '', offer: '', angle: '', platform: 'Meta' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const runs = useAsync(() => api.runs(`?brand_id=${brand.id}&limit=100`), [brand.id])
  const [ids, setIds] = useState([])
  const [stage, setStage] = useState('brief')
  async function save() {
    setBusy(true); setError('')
    try {
      const body = { title, brief, run_ids: ids, stage }
      if (campaign) await api.saveCampaign(brand.id, campaign, body)
      else setCampaign((await api.createCampaign(brand.id, body)).id)
      rows.reload()
      return true
    } catch (e) { setError(e.message); return false } finally { setBusy(false) }
  }
  async function launch(key) {
    if (!title.trim()) { setError('سمّ الحملة أولًا عشان نحفظ البريف قبل انتقالك.'); return }
    if (!await save()) return
    onModule(key, { product: brief.product, offer: brief.offer, platform: brief.platform,
      notes: `الجمهور: ${brief.audience}\nالعرض: ${brief.offer}\nالمنصة: ${brief.platform}\nالزاوية المختارة: ${brief.angle}\nالحملة: ${title}` })
  }
  return <div className="space-y-5">
    <h1 className="text-xl font-bold text-white">من منتج لحملة</h1>
    <p className="text-sm text-slate-400">احفظ البريف، اختَر زاويتك، ثم انقل نفس السياق لكتابة الكوبي والسكريبت والإنتاج.</p>
    {error && <Banner kind="error">{error}</Banner>}
    <div className="flex flex-wrap gap-2">{rows.data?.map(c => <button key={c.id} className="chip" onClick={() => { setCampaign(c.id); setTitle(c.title); setBrief(c.brief); setIds(c.run_ids); setStage(c.stage) }}>{c.title}</button>)}
      <button className="btn-ghost" onClick={() => { setCampaign(null); setTitle(''); setBrief({ product: '', audience: '', offer: '', angle: '', platform: 'Meta' }); setIds([]); setStage('brief') }}>+ حملة جديدة</button></div>
    <section className="card p-5 space-y-4">
      <label className="label">اسم الحملة<input className="input mt-1" value={title} onChange={e => setTitle(e.target.value)} /></label>
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="label">المنتج<select className="input mt-1" value={brief.product} onChange={e => setBrief({ ...brief, product: e.target.value })}><option value="">اختر المنتج</option>{brand.products.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}</select></label>
        <label className="label">المنصة<select className="input mt-1" value={brief.platform} onChange={e => setBrief({ ...brief, platform: e.target.value })}>{['Meta', 'TikTok', 'Google'].map(x => <option key={x}>{x}</option>)}</select></label>
      </div>
      {[['audience', 'الجمهور المستهدف'], ['offer', 'العرض والسعر'], ['angle', 'الزاوية المختارة بعد المراجعة']].map(([k, label]) => <label className="label block" key={k}>{label}<textarea className="input mt-1" rows={2} value={brief[k]} onChange={e => setBrief({ ...brief, [k]: e.target.value })} /></label>)}
      <label className="label">مرحلة الحملة<select className="input mt-1" value={stage} onChange={e => setStage(e.target.value)}>{[['brief', 'البريف'], ['angles', 'اختيار الزاوية'], ['copy', 'الكتابة'], ['production', 'الإنتاج'], ['review', 'المراجعة'], ['done', 'مكتملة']].map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <details><summary className="text-sm text-slate-300 cursor-pointer">اربط مخرجات المكتبة بالحملة</summary><div className="max-h-44 overflow-auto space-y-2 mt-2">{runs.data?.items.map(r => <label key={r.id} className="flex gap-2 text-sm text-slate-400"><input type="checkbox" checked={ids.includes(r.id)} onChange={e => setIds(e.target.checked ? [...ids, r.id] : ids.filter(id => id !== r.id))} />{r.title} — {new Date(r.created_at).toLocaleDateString('ar-EG')}</label>)}</div></details>
      <button className="btn-primary" disabled={busy || !title.trim() || brand.role === 'viewer'} onClick={save}>{busy && <Spinner />}حفظ الحملة</button>
    </section>
    <div className="grid gap-3 sm:grid-cols-3">
      {[['angle_generator', '1. اقترح زوايا'], ['hooks', '2. اكتب هوكات'], ['ad_copy', '3. اكتب الإعلان'], ['ad_script', '4. اكتب السكريبت'], ['landing_copy', '5. محتوى صفحة الهبوط']].map(([key, label]) => <button key={key} className="btn-ghost" onClick={() => launch(key)}>{label}</button>)}
      <button className="btn-primary" disabled={busy || brand.role === 'viewer'} onClick={async () => { if (!title.trim()) { setError('سمّ الحملة أولًا.'); return } if (await save()) onStudio({ kind: 'image', text: `${brief.product}\n${brief.offer}\n${brief.angle}` }) }}>6. إنتاج الملفات النهائية</button>
    </div>
  </div>
}
