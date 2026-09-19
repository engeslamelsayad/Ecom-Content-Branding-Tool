import { useState } from 'react'
import { Brain, MessageSquareQuote, Package, Swords, Trash2, UserRound, X } from 'lucide-react'
import { api } from '../api'
import { Banner, Markdown, Spinner } from '../components/ui'

/**
 * The persistent context every module inherits. Answer the intake once here,
 * and no module asks for it again.
 */
export default function BrandBrain({ brand, onChanged }) {
  const [error, setError] = useState('')
  const [open, setOpen] = useState(null)

  if (!brand) return null

  const wrap = (fn) => async (...args) => {
    try { await fn(...args); onChanged() } catch (err) { setError(err.message) }
  }

  const core = brand.core || {}

  return (
    <div className="space-y-5">
      {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}

      <Identity brand={brand} onSave={wrap((body) => api.patchBrand(brand.id, body))} />

      <div className="grid gap-5 md:grid-cols-2">
        <Collection
          icon={Package} title="المنتجات" items={brand.products}
          render={(p) => (
            <>
              <div className="text-sm text-white">{p.name}</div>
              <div className="text-xs text-slate-500">
                {p.price != null ? `${p.price} ${p.currency}` : 'من غير سعر'}
                {p.usp && ` · ${p.usp}`}
              </div>
            </>
          )}
          onAdd={wrap((body) => api.addChild(brand.id, 'products', body))}
          onDelete={wrap((id) => api.delChild(brand.id, 'products', id))}
          fields={[['name', 'اسم المنتج', 'text', true], ['price', 'السعر', 'number'],
                   ['cost', 'التكلفة', 'number'], ['usp', 'الميزة الفريدة', 'text'],
                   ['description', 'الوصف', 'textarea']]}
        />

        <Collection
          icon={UserRound} title="الأفاتارات" items={brand.avatars}
          render={(a) => (
            <>
              <div className="text-sm text-white">{a.name} {a.is_primary && <span className="chip ms-1">أساسي</span>}</div>
              <div className="text-xs text-slate-500 line-clamp-2">
                {Object.values(a.data || {}).join(' · ') || '—'}
              </div>
            </>
          )}
          onAdd={wrap((body) => {
            const { name, ...rest } = body
            return api.addChild(brand.id, 'avatars', { name, data: rest })
          })}
          onDelete={wrap((id) => api.delChild(brand.id, 'avatars', id))}
          fields={[['name', 'الاسم والعمر والمدينة', 'text', true],
                   ['desire', 'الرغبة الأساسية', 'text'], ['fear', 'الخوف الأساسي', 'text'],
                   ['trigger', 'لحظة التحوّل (الـ Trigger)', 'text'],
                   ['objections', 'أكبر 3 اعتراضات', 'textarea']]}
        />

        <Collection
          icon={Swords} title="المنافسون" items={brand.competitors}
          render={(c) => (
            <>
              <div className="text-sm text-white">{c.name} <span className="chip ms-1">{c.kind}</span></div>
              <div className="text-xs text-slate-500 line-clamp-2">
                {Object.values(c.data || {}).join(' · ') || '—'}
              </div>
            </>
          )}
          onAdd={wrap((body) => {
            const { name, kind, ...rest } = body
            return api.addChild(brand.id, 'competitors', { name, kind: kind || 'direct', data: rest })
          })}
          onDelete={wrap((id) => api.delChild(brand.id, 'competitors', id))}
          fields={[['name', 'اسم المنافس', 'text', true],
                   ['messaging', 'الرسالة الأساسية بتاعته', 'text'],
                   ['price', 'الشريحة السعرية', 'text'],
                   ['weakness', 'نقطة ضعفه', 'text']]}
        />

        <VocBank brand={brand} onChanged={onChanged} onError={setError} />
      </div>

      {Object.keys(core).length > 0 && (
        <section className="card">
          <header className="flex items-center gap-2 border-b border-ink-line px-5 py-3.5">
            <Brain className="w-4 h-4 text-brand-400" />
            <h2 className="font-semibold text-white flex-1">الاستراتيچية المعتمدة</h2>
            <span className="text-[11px] text-slate-500">كل موديول جديد بيرث الكلام ده</span>
          </header>
          <div className="p-5 space-y-2">
            {Object.entries(core).map(([key, value]) => (
              <div key={key} className="rounded-xl border border-ink-line bg-ink">
                <button onClick={() => setOpen(open === key ? null : key)}
                        className="w-full flex items-center gap-2 px-4 py-3 text-start">
                  <span className="flex-1 text-sm text-slate-200 font-medium">{key}</span>
                  <span className="text-[11px] text-slate-600">
                    {String(value).length.toLocaleString()} حرف
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm(`مسح "${key}" من ذاكرة البراند؟`)) {
                        api.clearCore(brand.id, key).then(onChanged).catch((x) => setError(x.message))
                      }
                    }}
                    className="text-slate-600 hover:text-rose-400">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </button>
                {open === key && (
                  <div className="border-t border-ink-line px-4 py-3 max-h-80 overflow-y-auto">
                    <Markdown text={String(value)} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

const DIALECTS = ['مصري', 'سعودي (حجازي)', 'خليجي/إماراتي', 'شامي', 'فصحى', 'English']

function Identity({ brand, onSave }) {
  const [form, setForm] = useState({
    name: brand.name, one_liner: brand.one_liner, industry: brand.industry,
    market: brand.market, dialect: brand.dialect, stage: brand.stage,
  })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <section className="card p-5">
      <h2 className="font-semibold text-white mb-4">هوية البراند</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div><label className="label">الاسم</label>
          <input className="input" value={form.name} onChange={set('name')} /></div>
        <div className="sm:col-span-2"><label className="label">وصف في سطر</label>
          <input className="input" value={form.one_liner} onChange={set('one_liner')} /></div>
        <div><label className="label">المجال</label>
          <input className="input" value={form.industry} onChange={set('industry')} /></div>
        <div><label className="label">السوق</label>
          <input className="input" value={form.market} onChange={set('market')} /></div>
        <div><label className="label">اللهجة الافتراضية</label>
          <select className="input" value={form.dialect} onChange={set('dialect')}>
            {DIALECTS.map((d) => <option key={d}>{d}</option>)}
          </select></div>
        <div><label className="label">المرحلة</label>
          <select className="input" value={form.stage} onChange={set('stage')}>
            <option value="launch">إطلاق جديد</option>
            <option value="redesign">إعادة تصميم</option>
            <option value="live">براند شغال</option>
          </select></div>
      </div>
      <button className="btn-primary mt-4"
              disabled={busy}
              onClick={async () => { setBusy(true); await onSave(form); setBusy(false) }}>
        {busy && <Spinner />} حفظ
      </button>
    </section>
  )
}

function Collection({ icon: Icon, title, items = [], render, onAdd, onDelete, fields }) {
  const [form, setForm] = useState({})
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)

  const required = fields.filter(([, , , req]) => req).map(([k]) => k)
  const ready = required.every((k) => String(form[k] || '').trim())

  async function submit() {
    setBusy(true)
    const payload = Object.fromEntries(
      Object.entries(form).filter(([, v]) => String(v || '').trim() !== '')
        .map(([k, v]) => [k, fields.find(([fk]) => fk === k)?.[2] === 'number' ? Number(v) : v]))
    await onAdd(payload)
    setForm({}); setAdding(false); setBusy(false)
  }

  return (
    <section className="card flex flex-col">
      <header className="flex items-center gap-2 border-b border-ink-line px-5 py-3.5">
        <Icon className="w-4 h-4 text-brand-400" />
        <h2 className="font-semibold text-white flex-1">{title}</h2>
        <span className="chip">{items.length}</span>
      </header>

      <div className="p-5 space-y-2 flex-1">
        {items.map((item) => (
          <div key={item.id} className="flex items-start gap-3 rounded-xl border border-ink-line
                                        bg-ink px-4 py-2.5">
            <div className="flex-1 min-w-0">{render(item)}</div>
            <button onClick={() => onDelete(item.id)} className="text-slate-600 hover:text-rose-400">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        {!items.length && !adding && <p className="text-sm text-slate-600">مفيش حاجة لسه.</p>}

        {adding && (
          <div className="space-y-3 rounded-xl border border-brand-500/30 bg-brand-500/5 p-4">
            {fields.map(([key, label, type, req]) => (
              <div key={key}>
                <label className="label">{label}{req && <span className="text-rose-400 ms-1">*</span>}</label>
                {type === 'textarea'
                  ? <textarea className="input" rows={2} value={form[key] || ''}
                              onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
                  : <input className="input" type={type === 'number' ? 'number' : 'text'}
                           value={form[key] || ''}
                           onChange={(e) => setForm({ ...form, [key]: e.target.value })} />}
              </div>
            ))}
            <div className="flex gap-2">
              <button className="btn-primary flex-1 !py-2 text-xs" disabled={!ready || busy}
                      onClick={submit}>{busy && <Spinner />} حفظ</button>
              <button className="btn-ghost !py-2 text-xs" onClick={() => setAdding(false)}>إلغاء</button>
            </div>
          </div>
        )}
      </div>

      {!adding && (
        <button className="border-t border-ink-line px-5 py-2.5 text-xs text-brand-300
                           hover:bg-brand-500/5 transition"
                onClick={() => setAdding(true)}>+ إضافة</button>
      )}
    </section>
  )
}

function VocBank({ brand, onChanged, onError }) {
  const [text, setText] = useState('')
  const [category, setCategory] = useState('motivation')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    try {
      await api.bulkVoc(brand.id, { text, category, source: 'review' })
      setText(''); onChanged()
    } catch (err) { onError(err.message) } finally { setBusy(false) }
  }

  return (
    <section className="card flex flex-col">
      <header className="flex items-center gap-2 border-b border-ink-line px-5 py-3.5">
        <MessageSquareQuote className="w-4 h-4 text-brand-400" />
        <h2 className="font-semibold text-white flex-1">بنك كلام العملاء</h2>
        <span className="chip">{brand.voc?.length || 0}</span>
      </header>

      <div className="p-5 space-y-3 flex-1">
        <p className="text-[11px] text-slate-500 leading-relaxed">
          الصق ريفيوهات حقيقية أو كومنتات — سطر لكل واحدة. الكلام ده بيتحط في الـ copy
          بالحرف بدل ما الموديل يتخيّل كلام عملاء.
        </p>

        <div className="space-y-2 max-h-44 overflow-y-auto">
          {(brand.voc || []).map((v) => (
            <div key={v.id} className="flex items-start gap-2 rounded-lg border border-ink-line
                                       bg-ink px-3 py-2">
              <span className="flex-1 text-xs text-slate-300">"{v.text}"</span>
              <button onClick={() => api.delChild(brand.id, 'voc', v.id).then(onChanged)}
                      className="text-slate-600 hover:text-rose-400">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>

        <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="motivation">دافع / ألم (M)</option>
          <option value="value">قيمة / ميزة (V)</option>
          <option value="anxiety">اعتراض / قلق (A)</option>
        </select>
        <textarea className="input" rows={3} placeholder="ريفيو في كل سطر…"
                  value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn-primary w-full !py-2 text-xs" disabled={!text.trim() || busy}
                onClick={submit}>{busy && <Spinner />} إضافة</button>
      </div>
    </section>
  )
}
