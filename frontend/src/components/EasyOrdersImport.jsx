import { useState } from 'react'
import { api } from '../api'
import { Banner, Spinner } from './ui'

export default function EasyOrdersImport({ brandId, onApplied }) {
  const [key, setKey] = useState('')
  const [currency, setCurrency] = useState('EGP')
  const [products, setProducts] = useState([])
  const [selected, setSelected] = useState({})
  const [page, setPage] = useState(0)
  const [startPage, setStartPage] = useState('1')
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(null)
  const [updateExisting, setUpdateExisting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [warning, setWarning] = useState('')
  const count = products.filter(p => selected[p.external_id]).length

  function reset(value) {
    setKey(value); setProducts([]); setSelected({}); setPage(0); setHasMore(false)
    setMessage(''); setError(''); setWarning(''); setTotal(null)
  }

  async function preview(nextPage, replace = false) {
    setBusy(true); setError(''); setMessage(''); setWarning('')
    try {
      const result = await api.easyOrdersPreview({ brand_id: brandId, api_key: key.trim(), page: nextPage })
      const prior = nextPage === 1 || replace ? [] : products
      const seen = new Set(prior.map(p => p.external_id))
      const fresh = result.products.filter(p => !seen.has(p.external_id))
      const merged = [...prior, ...fresh]
      setProducts(merged); setPage(nextPage); setTotal(result.total)
      const repeated = result.products.length > 0 && fresh.length === 0
      setHasMore(result.has_more && !repeated && merged.length < 500)
      setSelected(previous => ({ ...(nextPage === 1 || replace ? {} : previous),
        ...Object.fromEntries(fresh.map(p => [p.external_id, !p.exists])) }))
      if (repeated) setWarning('EasyOrders رجّع نفس المنتجات مرة تانية؛ وقفنا تحميل الصفحات لتجنب التكرار.')
      else if (result.skipped) setWarning(`تم تجاوز ${result.skipped} سجل ناقص الهوية أو مكرر في الصفحة.`)
      else if (merged.length >= 500 && result.has_more) setWarning('وصلت لحد المعاينة: 500 منتج. احفظ المحدد وابدأ سحب جديد من رقم الصفحة التالية.')
      if (!merged.length) setMessage('مفيش منتجات في الصفحة دي. راجع المتجر أو جرّب رقم صفحة مختلف.')
      else if (!fresh.length && !repeated) setMessage('وصلت لنهاية المنتجات.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function apply() {
    setBusy(true); setError(''); setMessage('')
    try {
      const chosen = products.filter(p => selected[p.external_id]).map(({ exists: _exists, selling_price: _price, ...p }) => p)
      const result = await api.easyOrdersApply({ brand_id: brandId, products: chosen, currency, update_existing: updateExisting })
      setMessage(`تمت إضافة ${result.added} منتج، وتحديث ${result.updated}، وتجاوز ${result.skipped} موجود بالفعل.`)
      setProducts(previous => previous.map(p => selected[p.external_id] ? { ...p, exists: true } : p))
      setSelected({})
      onApplied()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return <div className="space-y-4">
    <Banner kind="info">من لوحة EasyOrders: الإعدادات ← Public API ← مفتاح جديد. فعّل <strong>الوصول إلى المنتجات</strong> فقط واحفظ المفتاح وهو مفعّل.</Banner>
    <p className="text-xs text-slate-400">نسحب الاسم والوصف والأسعار وروابط الصور والمخزون والاختيارات المتاحة. المفتاح لا يُحفظ، والسحب لا يحتاج AI. العملة بتحددها أنت لأن رد المنتجات لا يضمن إرسالها.</p>
    <a href="https://public-api-docs.easy-orders.net/docs/authentication" target="_blank" rel="noreferrer" className="text-xs text-brand-300 underline">طريقة إنشاء المفتاح في EasyOrders</a>
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="sm:col-span-2 label">مفتاح EasyOrders Public API
        <input className="input mt-1" dir="ltr" type="password" autoComplete="new-password" value={key} disabled={busy}
          onChange={e => reset(e.target.value)} placeholder="Api-Key" />
      </label>
      <label className="label">عملة أسعار المتجر
        <select className="input mt-1" value={currency} onChange={e => setCurrency(e.target.value)} disabled={busy}>
          {['EGP', 'SAR', 'AED', 'USD', 'KWD', 'QAR', 'BHD', 'OMR', 'JOD', 'MAD', 'DZD', 'TND', 'EUR'].map(c => <option key={c}>{c}</option>)}
        </select>
      </label>
    </div>
    <button className="btn-primary w-full" disabled={busy || !key.trim()} onClick={() => preview(1)}>{busy && <Spinner />} سحب ومعاينة المنتجات</button>
    {error && <Banner kind="error">{error}</Banner>}
    {message && <Banner kind="success">{message}</Banner>}
    {warning && <Banner kind="info">{warning}</Banner>}
    {!!products.length && <div className="space-y-3 border-t border-ink-line pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm text-white">معاينة {products.length} منتج{total != null && ` من ${total}`} · محدد {count}</h3>
        <button className="btn-ghost text-xs" disabled={busy} onClick={() => setSelected(Object.fromEntries(products.map(p => [p.external_id, true])))}>تحديد الكل</button>
        <button className="btn-ghost text-xs" disabled={busy} onClick={() => setSelected({})}>إلغاء التحديد</button>
      </div>
      <div className="max-h-[32rem] overflow-y-auto space-y-2">
        {products.map(p => <div key={p.external_id} className="rounded-xl border border-ink-line p-3 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" className="mt-1 accent-brand-500" disabled={busy} checked={!!selected[p.external_id]}
              onChange={e => setSelected(s => ({ ...s, [p.external_id]: e.target.checked }))} />
            {p.images[0] && <img src={p.images[0]} alt="" loading="lazy" referrerPolicy="no-referrer" className="w-14 h-14 rounded-lg object-contain bg-white shrink-0" />}
            <span className="min-w-0 flex-1 space-y-1">
              <span className="block text-sm text-white break-words">{p.name} {p.exists && <span className="chip">مستورد بالفعل</span>}</span>
              <span className="block text-xs text-slate-300">{p.selling_price == null ? 'السعر غير متاح' : `${p.selling_price} ${currency}`}
                {p.price != null && p.price !== p.selling_price && <del className="ms-2 text-slate-500">{p.price} {currency}</del>}</span>
              {p.sku && <span className="block text-xs text-slate-500 break-all">SKU: {p.sku}</span>}
            </span>
          </label>
          <details className="text-xs text-slate-400"><summary className="cursor-pointer">الوصف والصور والاختيارات</summary>
            <p className="mt-2 whitespace-pre-wrap break-words">{p.description || 'الوصف غير متاح'}</p>
            {p.categories.length > 0 && <p className="mt-2">الأقسام: {p.categories.join('، ')}</p>}
            {p.options.map((o, i) => <p key={i} className="mt-1">{o}</p>)}
            {p.quantity != null && <p className="mt-1">المخزون وقت السحب: {p.quantity}</p>}
            <p className="mt-1">{p.images.length} صورة · {p.variants.length} اختيار منتج</p>
            {!!p.variants.length && <ul className="mt-2 space-y-1">{p.variants.map((v, i) => <li key={i}>{v.label || `اختيار ${i + 1}`} — {v.price ?? 'بدون سعر'} {currency}{v.sale_price > 0 && ` · سعر الخصم: ${v.sale_price} ${currency}`}</li>)}</ul>}
          </details>
        </div>)}
      </div>
      {hasMore && <button className="btn-ghost w-full" disabled={busy} onClick={() => preview(page + 1)}>{busy && <Spinner />} تحميل الصفحة التالية</button>}
      <label className="flex items-start gap-2 text-xs text-slate-300"><input type="checkbox" className="accent-brand-500" disabled={busy} checked={updateExisting} onChange={e => setUpdateExisting(e.target.checked)} />تحديث بيانات المنتجات المستوردة سابقًا لو محددة، مع الاحتفاظ بالتكلفة والميزة الفريدة اللي كتبتها. بدون الاختيار ده بنتجاوز المنتجات الموجودة.</label>
      <p className="text-xs text-slate-500">سعر الخصم الصالح يصبح سعر المنتج. الصور محفوظة كروابط للمصدر، والمخزون لقطة وقت السحب. المنتجات اليدوية لا يتم دمجها تلقائيًا.</p>
      <button className="btn-primary w-full" disabled={busy || !count} onClick={apply}>{busy && <Spinner />} حفظ {count} منتج محدد في الـ Brand Brain</button>
    </div>}
    <details className="text-xs text-slate-500"><summary className="cursor-pointer">استكمال من صفحة معينة</summary>
      <div className="mt-2 flex gap-2 items-center">
        <label>رقم الصفحة <input aria-label="رقم صفحة EasyOrders" className="input !w-24" type="number" min="1" max="10000" value={startPage} onChange={e => setStartPage(e.target.value)} disabled={busy} /></label>
        <button className="btn-ghost" disabled={busy || !key.trim() || !Number.isInteger(Number(startPage)) || Number(startPage) < 1 || Number(startPage) > 10000} onClick={() => preview(Number(startPage), true)}>فتح الصفحة</button>
      </div>
    </details>
  </div>
}
