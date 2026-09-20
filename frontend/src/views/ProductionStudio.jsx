import { useEffect, useRef, useState } from 'react'
import { Download, Film, Image as ImageIcon, Mic, Plus, Settings, Sparkles, Trash2 } from 'lucide-react'
import { api } from '../api'
import { Banner, Spinner } from '../components/ui'

const STATES = { queued: 'في الانتظار', submitting: 'إرسال للمزود', running: 'قيد الإنتاج', done: 'جاهز',
  error: 'تعذّر الإنتاج', cancelled: 'تم الإلغاء', needs_attention: 'يحتاج مراجعة' }
const ACTIVE = ['queued', 'running', 'submitting', 'cancel_requested']

export default function ProductionStudio({ brand, user, seed }) {
  const [kind, setKind] = useState(seed?.kind || 'image')
  const [prompt, setPrompt] = useState(seed?.text || '')
  const [voiceover, setVoiceover] = useState(seed?.kind === 'audio' ? seed.text : '')
  const [voice, setVoice] = useState('Rachel')
  const [language, setLanguage] = useState('ar')
  const [ratio, setRatio] = useState('9:16')
  const [scenes, setScenes] = useState([{ prompt: '', duration: 5 }])
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [connection, setConnection] = useState(null)
  const [jobs, setJobs] = useState([])
  const [offset, setOffset] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const requestId = useRef(null)
  const sending = useRef(false)

  const refresh = async () => {
    const [c, list] = await Promise.all([api.connection(), api.production(brand.id, offset)])
    setConnection(c); setJobs(list.items)
  }
  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const [c, list] = await Promise.all([api.connection(), api.production(brand.id, offset)])
        if (alive) { setConnection(c); setJobs(list.items) }
      } catch (e) { if (alive) setError(e.message) }
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [brand.id, offset])

  async function produce() {
    if (sending.current) return
    sending.current = true
    setBusy(true); setError(''); setNotice('')
    try {
      // Reuse the same id after an uncertain network response to avoid double billing.
      requestId.current ||= crypto.randomUUID()
      const reference = file ? await api.uploadAsset(brand.id, file, 'image') : null
      await api.createProduction({ brand_id: brand.id, idempotency_key: requestId.current,
        title, kind, prompt, voiceover, voice, language, aspect_ratio: ratio,
        scenes: kind === 'video' ? scenes : [], confirmed,
        source_run_id: seed?.runId || null, reference_asset_id: reference?.id || null })
      requestId.current = null
      setConfirmed(false); setNotice('بدأ الطلب. تقدر تقفل الصفحة وترجع تلاقي حالته وملفه هنا.')
      await refresh()
    } catch (e) { setError(e.message) } finally { setBusy(false); sending.current = false }
  }

  return <div className="space-y-6">
    <div className="flex items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold text-white">استوديو الإنتاج</h1>
        <p className="text-sm text-slate-400 mt-1">حوّل فكرتك أو السكريبت إلى تصميم، صوت أو فيديو قابل للتنزيل.</p></div>
      {user.role === 'owner' && <button className="btn-ghost" onClick={() => setShowSettings(!showSettings)}><Settings className="w-4 h-4" />اتصال API</button>}
    </div>
    {showSettings && <ConnectionPanel onSaved={refresh} configured={connection?.configured} />}
    {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}
    {notice && <Banner kind="success">{notice}</Banner>}
    {connection && !connection.configured && <Banner kind="warn">الإنتاج جاهز للإعداد. {user.role === 'owner' ? 'افتح اتصال API وأضف مفتاح fal.' : 'اطلب من المالك تفعيل اتصال الإنتاج.'} كتابة السكريبتات متاحة من تبويب Content.</Banner>}
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="card p-5 space-y-4">
        <div className="flex flex-wrap gap-2">
          {[['image', 'تصميم نهائي', ImageIcon], ['audio', 'تعليق صوتي', Mic], ['video', 'فيديو نهائي', Film]].map(([id, label, Icon]) =>
            <button key={id} className={kind === id ? 'btn-primary' : 'btn-ghost'} onClick={() => { setKind(id); setConfirmed(false) }}><Icon className="w-4 h-4" />{label}</button>)}
        </div>
        <label className="label">اسم المخرج<input className="input mt-1" value={title} onChange={e => setTitle(e.target.value)} placeholder="مثال: إعلان المنتج — تجربة 1" /></label>
        {seed?.text && kind === 'video' && <details className="text-sm text-slate-400"><summary className="cursor-pointer">السكريبت المصدر — استخدمه لتقسيم المشاهد والنص المنطوق</summary><pre className="whitespace-pre-wrap max-h-48 overflow-auto p-3">{seed.text}</pre></details>}
        {kind === 'image' && <label className="label">وصف التصميم والنص المطلوب ظهوره<textarea className="input mt-1" rows={6} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="صف المنتج، الخلفية، الألوان، ترتيب العناصر والنص النهائي…" /></label>}
        {kind === 'video' && <div className="space-y-3">
          <p className="text-xs text-slate-400">قسّم الإعلان إلى مشاهد؛ حتى 6 مشاهد، كل مشهد 5 أو 10 ثوانٍ. نجمعها في ملف واحد.</p>
          {scenes.map((scene, i) => <div key={i} className="rounded-xl border border-ink-line p-3 space-y-2">
            <div className="flex items-center justify-between"><span className="text-sm text-white">مشهد {i + 1}</span>
              {scenes.length > 1 && <button aria-label={`حذف مشهد ${i + 1}`} onClick={() => setScenes(scenes.filter((_, n) => n !== i))}><Trash2 className="w-4 h-4" /></button>}</div>
            <textarea aria-label={`وصف مشهد ${i + 1}`} className="input" rows={3} value={scene.prompt} placeholder="وصف الصورة والحركة؛ الكلام المنطوق له حقل منفصل أسفل المشاهد." onChange={e => setScenes(scenes.map((s, n) => n === i ? { ...s, prompt: e.target.value } : s))} />
            <select aria-label={`مدة مشهد ${i + 1}`} className="input" value={scene.duration} onChange={e => setScenes(scenes.map((s, n) => n === i ? { ...s, duration: Number(e.target.value) } : s))}><option value={5}>5 ثوانٍ</option><option value={10}>10 ثوانٍ</option></select>
          </div>)}
          {scenes.length < 6 && <button className="btn-ghost" onClick={() => setScenes([...scenes, { prompt: '', duration: 5 }])}><Plus className="w-4 h-4" />إضافة مشهد</button>}
        </div>}
        {kind !== 'image' && <>
          <label className="label">النص المنطوق {kind === 'video' ? '(اختياري)' : ''}<textarea className="input mt-1" rows={5} maxLength={5000} value={voiceover} onChange={e => setVoiceover(e.target.value)} placeholder="اكتب الكلام الذي سيُسمع فقط، بدون وصف مشاهد أو جدول السكريبت." /></label>
          <div className="grid grid-cols-2 gap-3"><label className="label">الصوت<select className="input mt-1" value={voice} onChange={e => setVoice(e.target.value)}>{['Rachel', 'Aria', 'Roger', 'Sarah', 'George'].map(v => <option key={v}>{v}</option>)}</select></label>
            <label className="label">لغة الصوت<select className="input mt-1" value={language} onChange={e => setLanguage(e.target.value)}><option value="ar">العربية</option><option value="en">English</option></select></label></div>
          <p className="text-xs text-slate-500">الصوت مولّد بالذكاء الاصطناعي. راجع النطق قبل النشر. في الفيديو نمد آخر لقطة إذا احتاج التعليق وقتًا أطول.</p>
        </>}
        {kind !== 'audio' && <>
          <label className="label">المقاس<select className="input mt-1" value={ratio} onChange={e => setRatio(e.target.value)}><option value="9:16">9:16 — Reels / Stories</option><option value="1:1">1:1 — مربع</option><option value="16:9">16:9 — أفقي</option></select></label>
          <label className="label">صورة المنتج المرجعية (اختيارية)<input className="input mt-1" type="file" accept="image/*" onChange={e => setFile(e.target.files?.[0] || null)} /></label>
          <p className="text-xs text-slate-500">الصورة تساعد على ثبات شكل المنتج. راجع التفاصيل والنصوص في الناتج قبل استخدامه.</p>
        </>}
        <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />راجعت النصوص وأوافق على إرسالها والصورة المرجعية إلى fal وعلى تكلفة الإنتاج في حساب المزود.</label>
        <button className="btn-primary w-full" disabled={busy || !confirmed || !connection?.configured || brand.role === 'viewer'} onClick={produce}>{busy ? <Spinner /> : <Sparkles className="w-4 h-4" />}إنتاج {kind === 'image' ? 'التصميم' : kind === 'audio' ? 'الصوت' : 'الفيديو'}</button>
      </section>
      <aside className="card p-5 space-y-4 h-fit text-sm text-slate-400">
        <h2 className="text-white font-semibold">اختيارك محفوظ: نص أو إنتاج</h2>
        <p>استخدم موديولات Content لكتابة السكريبت، ثم زر «حوّل لإنتاج» لمراجعته وإنتاج الملف النهائي.</p>
        <p>الصور: Nano Banana Pro<br />الفيديو: Kling 2.6<br />الصوت: ElevenLabs v3</p>
        <p>كل مشهد وتعليق صوتي طلب منفصل مدفوع. لا نعرض سعرًا تخمينيًا كأنه فاتورة.</p>
        <a href="https://fal.ai/pricing" target="_blank" rel="noreferrer" className="text-brand-300 underline">تسعير fal ورصيد الحساب</a>
        <p>حتى {connection?.daily_limit ?? '—'} طلب يوميًا و{connection?.max_active ?? '—'} جاريين لكل عميل. الإلغاء قد لا يمنع تكلفة مرحلة بدأت عند المزود.</p>
      </aside>
    </div>
    <section className="space-y-3"><h2 className="text-lg font-semibold text-white">مكتبة الإنتاج</h2>
      {!jobs.length && <p className="text-slate-500 text-sm">ملفات البراند ستظهر هنا بعد أول إنتاج.</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{jobs.map(job => <article key={job.id} className="card p-4 space-y-3">
        <div className="flex gap-2 justify-between"><h3 className="font-medium text-white">{job.title}</h3><span className="chip">{STATES[job.status] || job.status}</span></div>
        {job.asset_id && (job.kind === 'image' ? <img className="w-full max-h-72 object-contain rounded-lg" src={api.assetUrl(job.asset_id)} alt={job.title} /> : job.kind === 'audio' ? <audio className="w-full" controls src={api.assetUrl(job.asset_id)} /> : <video className="w-full max-h-80 rounded-lg" controls src={api.assetUrl(job.asset_id)} />)}
        <p className="text-xs text-slate-500">{job.completed_steps}/{job.total_steps} مراحل مكتملة</p>
        {job.error && <p className="text-xs text-amber-200">{job.error}</p>}
        {job.asset_id && <a className="btn-ghost" href={api.assetUrl(job.asset_id, true)}><Download className="w-4 h-4" />تنزيل الملف</a>}
        {job.can_finalize && brand.role !== 'viewer' && <button className="btn-ghost" onClick={async () => { try { await api.finalizeProduction(job.id); await refresh() } catch (e) { setError(e.message) } }}>إعادة التجميع بدون توليد مدفوع</button>}
        {ACTIVE.includes(job.status) && <button className="btn-ghost" onClick={async () => { try { await api.cancelProduction(job.id); await refresh() } catch (e) { setError(e.message) } }}>طلب إلغاء</button>}
      </article>)}</div>
      <div className="flex gap-2"><button className="btn-ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>السابق</button><button className="btn-ghost" disabled={jobs.length < 50} onClick={() => setOffset(offset + 50)}>التالي</button></div>
    </section>
  </div>
}

function ConnectionPanel({ onSaved, configured }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  async function act(fn) { setBusy(true); setError(''); setMessage(''); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <section className="card p-5 space-y-3">
    <h2 className="font-semibold text-white">اتصال fal — إعداد المالك</h2>
    <p className="text-sm text-slate-400">مفتاح واحد للصور والفيديو والصوت. يُحفظ مشفرًا في الخادم ولا يرجع للمتصفح. {configured ? 'يوجد مفتاح محفوظ.' : 'لم يُضف مفتاح بعد.'}</p>
    <a className="text-sm text-brand-300 underline" href="https://fal.ai/dashboard/keys" target="_blank" rel="noreferrer">إنشاء مفتاح في حساب fal</a>
    <input className="input" aria-label="مفتاح fal API" type="password" autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)} placeholder="FAL_KEY" />
    <div className="flex gap-2"><button className="btn-primary" disabled={busy || !key.trim()} onClick={() => act(async () => { await api.saveConnection(key); setKey(''); setMessage('تم حفظ المفتاح مشفرًا.'); await onSaved() })}>حفظ المفتاح</button>
      <button className="btn-ghost" disabled={busy || !configured} onClick={() => act(async () => setMessage((await api.checkConnection()).message))}>فحص اتصال بدون توليد</button></div>
    {message && <Banner kind="success">{message}</Banner>}{error && <Banner kind="error">{error}</Banner>}
  </section>
}
