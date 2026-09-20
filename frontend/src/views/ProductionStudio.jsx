import { useEffect, useRef, useState } from 'react'
import { Download, Film, Image as ImageIcon, Mic, PenLine, Plus, Settings, Sparkles, Trash2, UserRound } from 'lucide-react'
import { api } from '../api'
import { Banner, Spinner } from '../components/ui'
import ProductionConnections, { IMAGE_MODELS } from '../components/ProductionConnections'

const STATES = { queued: 'في الانتظار', submitting: 'إرسال للمزود', running: 'قيد الإنتاج', done: 'جاهز', error: 'تعذّر الإنتاج', cancelled: 'تم الإلغاء', needs_attention: 'يحتاج مراجعة' }
const ACTIVE = ['queued', 'running', 'submitting', 'cancel_requested']
const FORMATS = { review: 'مراجعة وعرض المنتج', unboxing: 'فتح العبوة — Unboxing', tutorial: 'شرح الاستخدام', try_on: 'تجربة لبس — Try-on' }
const freshScene = () => ({ prompt: '', spoken_text: '', duration: 10 })

export default function ProductionStudio({ brand, user, seed, onContent }) {
  const [mode, setMode] = useState(seed?.kind === 'video' ? 'video' : seed?.kind === 'audio' ? 'audio' : 'product')
  const [prompt, setPrompt] = useState(seed?.text || '')
  const [voiceover, setVoiceover] = useState(seed?.kind === 'audio' ? seed.text : '')
  const [voice, setVoice] = useState('Rachel')
  const [language, setLanguage] = useState('ar')
  const [ratio, setRatio] = useState('9:16')
  const [scenes, setScenes] = useState([freshScene()])
  const [file, setFile] = useState(null)
  const [creatorFile, setCreatorFile] = useState(null)
  const [editAsset, setEditAsset] = useState(null)
  const [imageModel, setImageModel] = useState('default')
  const [quality, setQuality] = useState('high')
  const [format, setFormat] = useState('review')
  const [captions, setCaptions] = useState(false)
  const [brief, setBrief] = useState(seed?.text || '')
  const [sceneCount, setSceneCount] = useState(3)
  const [planning, setPlanning] = useState(false)
  const [title, setTitle] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [connection, setConnection] = useState(null)
  const [jobs, setJobs] = useState([])
  const [offset, setOffset] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const pending = useRef(null)
  const sending = useRef(false)
  const kind = ['product', 'ad'].includes(mode) ? 'image' : mode === 'audio' ? 'audio' : 'video'
  const ugc = mode === 'ugc'
  const resolvedModel = imageModel === 'default' ? connection?.defaults?.image_model || 'nano_banana' : imageModel
  const providers = [...new Set([kind === 'image' ? resolvedModel === 'nano_banana' ? 'fal' : 'openai' : ugc ? 'higgsfield' : 'fal', ...(kind === 'video' && captions ? ['openai'] : [])])]
  const missing = providers.filter(p => !connection?.connections?.[p]?.configured)
  const viewer = brand.role === 'viewer'
  const updateScene = (i, patch) => setScenes(scenes.map((s, n) => n === i ? { ...s, ...patch } : s))
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
  function changeMode(next) {
    setMode(next); setConfirmed(false); setCaptions(false)
    if (next === 'video') setScenes(s => s.map(x => ({ ...x, duration: Math.min(10, x.duration) })))
  }
  async function draft() {
    setPlanning(true); setError('')
    try {
      const plan = await api.planProduction({ brand_id: brand.id, brief, ugc_format: format, language, scene_count: sceneCount })
      setScenes(plan.scenes); setTitle(plan.title); setConfirmed(false)
      setNotice('المسودة جاهزة للمراجعة والتعديل. لم يتم توليد فيديو بعد.')
    } catch (e) { setError(e.message) } finally { setPlanning(false) }
  }
  async function produce() {
    if (sending.current) return
    sending.current = true
    setBusy(true); setError(''); setNotice('')
    try {
      // Freeze the payload as well as its key after an uncertain network response.
      if (!pending.current) {
        const reference = kind !== 'audio' && file ? await api.uploadAsset(brand.id, file, 'image') : editAsset
        const creator = ugc && creatorFile ? await api.uploadAsset(brand.id, creatorFile, 'image') : null
        pending.current = { brand_id: brand.id, idempotency_key: crypto.randomUUID(), title, kind, prompt,
          voiceover: ugc || kind === 'image' ? '' : voiceover, voice, language, aspect_ratio: ratio,
          scenes: kind === 'video' ? scenes : [], confirmed, image_model: resolvedModel, image_quality: quality,
          image_purpose: mode === 'ad' ? 'ad' : 'product', video_mode: ugc ? 'ugc' : 'product', ugc_format: format,
          captions: kind === 'video' && captions, creator_asset_id: creator?.id || null,
          source_run_id: seed?.runId || null, reference_asset_id: kind === 'audio' ? null : reference?.id || null }
      }
      await api.createProduction(pending.current)
      pending.current = null
      setConfirmed(false); setNotice('بدأ الطلب. تقدر تقفل الصفحة وترجع تلاقي حالته وملفه هنا.')
      await refresh()
    } catch (e) {
      if (e.status && e.status < 500) pending.current = null
      setError(e.message)
    } finally { setBusy(false); sending.current = false }
  }
  async function act(action) { try { await action(); await refresh() } catch (e) { setError(e.message) } }

  return <div className="space-y-6">
    <div className="flex items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold text-white">استوديو الإنتاج</h1><p className="text-sm text-slate-400 mt-1">اختار النتيجة، جهّز المراجع، وراجع المحتوى قبل الإنتاج.</p></div>
      {user.role === 'owner' && <button className="btn-ghost" onClick={() => setShowSettings(!showSettings)}><Settings className="w-4 h-4" />اتصالات وإعدادات الإنتاج</button>}
    </div>
    {showSettings && <ProductionConnections onSaved={refresh} settings={connection} />}
    {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}
    {notice && <Banner kind="success">{notice}</Banner>}
    {pending.current && !busy && <Banner kind="warn">لم نتأكد من استلام الطلب. إعادة التحقق تستخدم نفس الطلب كما أُرسل لتجنب تكرار التكلفة.<button className="btn-ghost" onClick={produce}>إعادة التحقق من الطلب</button></Banner>}
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="card p-5 space-y-4">
        <fieldset disabled={busy || planning || Boolean(pending.current)} className="space-y-4 disabled:opacity-60">
          <div className="flex flex-wrap gap-2">
            {[['product', 'صور منتجات', ImageIcon], ['ad', 'إعلان بصورة', ImageIcon], ['ugc', 'UGC بمقدم', UserRound], ['video', 'لقطات منتج', Film], ['audio', 'تعليق صوتي', Mic]].map(([id, label, Icon]) => <button key={id} className={mode === id ? 'btn-primary' : 'btn-ghost'} onClick={() => changeMode(id)}><Icon className="w-4 h-4" />{label}</button>)}
            <button className="btn-ghost" onClick={onContent}><PenLine className="w-4 h-4" />سكريبت فقط</button>
          </div>
          <label className="label">اسم المخرج<input className="input mt-1" value={title} maxLength={200} onChange={e => setTitle(e.target.value)} placeholder="إعلان المنتج — تجربة 1" /></label>
          {kind === 'image' && <>
            {editAsset && <div className="flex items-center gap-3 text-sm"><img className="w-20 h-20 object-contain rounded" src={api.assetUrl(editAsset.id)} alt="الصورة المطلوب تعديلها" /><span>تعديل على صورة من المكتبة؛ الأصل محفوظ.</span><button className="btn-ghost" onClick={() => setEditAsset(null)}>إزالة المرجع</button></div>}
            <label className="label">{editAsset ? 'التعديلات المطلوبة' : mode === 'ad' ? 'فكرة الإعلان والنص المطلوب ظهوره' : 'وصف صورة المنتج'}<textarea className="input mt-1" rows={5} maxLength={5000} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="صف الخلفية والإضاءة والتكوين، وحدد التفاصيل التي يجب الحفاظ عليها…" /></label>
            <details className="rounded-xl border border-ink-line p-3"><summary className="cursor-pointer text-sm">إعدادات متقدمة — {IMAGE_MODELS[resolvedModel]}</summary><div className="grid sm:grid-cols-2 gap-3 mt-3">
              <label className="label">موديل الصور<select className="input mt-1" value={imageModel} onChange={e => setImageModel(e.target.value)}><option value="default">إعداد المالك الافتراضي</option>{Object.entries(IMAGE_MODELS).map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label>
              {resolvedModel !== 'nano_banana' && <label className="label">الجودة<select className="input mt-1" value={quality} onChange={e => setQuality(e.target.value)}><option value="high">عالية — مخرج نهائي</option><option value="medium">متوسطة — معاينة</option></select></label>}
            </div><p className="text-xs text-slate-500 mt-2">Sunburst لدقة التعديل، Flare للسرعة. المقارنة على منتجك تحدد الاختيار الأنسب.</p></details>
          </>}
          {ugc && <>
            <div className="grid sm:grid-cols-2 gap-3"><label className="label">نوع الإعلان<select className="input mt-1" value={format} onChange={e => setFormat(e.target.value)}>{Object.entries(FORMATS).map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label><Language value={language} onChange={setLanguage} /></div>
            <label className="label">صورة مقدم الإعلان<input className="input mt-1" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setCreatorFile(e.target.files?.[0] || null)} /></label>
            <details className="rounded-xl border border-ink-line p-3" open><summary className="cursor-pointer text-sm">مساعد تجهيز السكريبت والمشاهد</summary>
              <label className="label mt-3">وصف المنتج، الفوائد المؤكدة والهدف<textarea className="input mt-1" rows={3} value={brief} maxLength={6000} onChange={e => setBrief(e.target.value)} placeholder="اسم المنتج وفائدته والدعوة لاتخاذ إجراء…" /></label>
              <div className="flex flex-wrap gap-3 mt-3"><label className="label">عدد المشاهد<select className="input" value={sceneCount} onChange={e => setSceneCount(Number(e.target.value))}>{[1, 2, 3, 4, 5, 6].map(n => <option key={n}>{n}</option>)}</select></label><button className="btn-ghost self-end" disabled={planning || viewer || brief.trim().length < 10 || !connection?.planner_configured} onClick={draft}>{planning ? <Spinner /> : <Sparkles className="w-4 h-4" />}تجهيز مسودة</button></div>
              <p className="text-xs text-slate-500 mt-2">المسودة تستخدم اتصال مساعد الكتابة وتكلفته. تقدر تكتب المشاهد يدويًا؛ الفيديو يبدأ بعد مراجعتك.</p>
            </details>
          </>}
          {seed?.text && kind === 'video' && <details className="text-sm text-slate-400"><summary>السكريبت المصدر</summary><pre className="whitespace-pre-wrap max-h-48 overflow-auto p-3">{seed.text}</pre></details>}
          {kind === 'video' && <div className="space-y-3">
            <p className="text-xs text-slate-400">حتى 6 مشاهد. {ugc ? 'اكتب الكلام داخل كل مشهد؛ الصوت يتولد مع حركة المقدم.' : 'الكلام المنطوق له حقل منفصل أسفل المشاهد.'}</p>
            {scenes.map((scene, i) => <div key={i} className="rounded-xl border border-ink-line p-3 space-y-2">
              <div className="flex items-center justify-between"><span className="text-sm text-white">مشهد {i + 1}</span>{scenes.length > 1 && <button aria-label={`حذف مشهد ${i + 1}`} onClick={() => setScenes(scenes.filter((_, n) => n !== i))}><Trash2 className="w-4 h-4" /></button>}</div>
              <textarea aria-label={`وصف مشهد ${i + 1}`} className="input" rows={3} value={scene.prompt} maxLength={2300} placeholder="وصف الصورة والحركة وما يفعله المقدم…" onChange={e => updateScene(i, { prompt: e.target.value })} />
              {ugc && <label className="label">الكلام المنطوق<textarea className="input mt-1" rows={2} maxLength={1000} value={scene.spoken_text || ''} onChange={e => updateScene(i, { spoken_text: e.target.value })} /><span className="text-xs text-slate-500">{scene.spoken_text?.trim().split(/\s+/).filter(Boolean).length || 0} كلمة — الحد {scene.duration * 3}</span></label>}
              <select aria-label={`مدة مشهد ${i + 1}`} className="input" value={scene.duration} onChange={e => updateScene(i, { duration: Number(e.target.value) })}>{(ugc ? [5, 10, 15] : [5, 10]).map(n => <option key={n} value={n}>{n} ثوانٍ</option>)}</select>
            </div>)}
            {scenes.length < 6 && <button className="btn-ghost" onClick={() => setScenes([...scenes, freshScene()])}><Plus className="w-4 h-4" />إضافة مشهد</button>}
          </div>}
          {kind !== 'image' && !ugc && <>
            <label className="label">النص المنطوق {kind === 'video' ? '(اختياري)' : ''}<textarea className="input mt-1" rows={4} maxLength={5000} value={voiceover} onChange={e => { setVoiceover(e.target.value); if (!e.target.value.trim()) setCaptions(false) }} placeholder="الكلام الذي سيُسمع فقط، بدون وصف مشاهد أو جدول." /></label>
            <div className="grid grid-cols-2 gap-3"><label className="label">الصوت<select className="input mt-1" value={voice} onChange={e => setVoice(e.target.value)}>{['Rachel', 'Aria', 'Roger', 'Sarah', 'George'].map(v => <option key={v}>{v}</option>)}</select></label><Language value={language} onChange={setLanguage} /></div>
          </>}
          {kind !== 'audio' && <>
            <label className="label">المقاس<select className="input mt-1" value={ratio} onChange={e => setRatio(e.target.value)}><option value="9:16">9:16 — Reels / Stories</option><option value="1:1">1:1 — مربع</option><option value="16:9">16:9 — أفقي</option></select></label>
            <label className="label">{ugc ? 'صورة المنتج — مطلوبة' : 'صورة مرجعية للمنتج أو التصميم (اختيارية)'}<input className="input mt-1" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { setFile(e.target.files?.[0] || null); setEditAsset(null) }} /></label>
          </>}
          {kind === 'video' && <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={captions} disabled={!ugc && !voiceover.trim()} onChange={e => setCaptions(e.target.checked)} />كابشن مدمج بتوقيت الكلام الفعلي — يحتاج اتصال OpenAI للتفريغ</label>}
          {connection && missing.length > 0 && <Banner kind="warn">هذا الاختيار يحتاج تفعيل: {missing.join(' + ')}. {user.role === 'owner' ? 'أضف المفاتيح من اتصالات الإنتاج.' : 'اطلب من المالك تفعيل الاتصال.'}</Banner>}
          <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />راجعت المحتوى وأوافق على إرسال النصوص والمراجع إلى {providers.join(' + ')} وعلى تكلفة الإنتاج في حساب المزود.</label>
          <button className="btn-primary w-full" disabled={busy || planning || !confirmed || missing.length > 0 || !connection || viewer || (ugc && (!creatorFile || !file))} onClick={produce}>{busy ? <Spinner /> : <Sparkles className="w-4 h-4" />}إنتاج {kind === 'image' ? 'الصورة' : kind === 'audio' ? 'الصوت' : 'الفيديو'}</button>
        </fieldset>
      </section>
      <aside className="card p-5 space-y-4 h-fit text-sm text-slate-400">
        <h2 className="text-white font-semibold">من السكريبت للملف النهائي</h2>
        <p>{ugc ? 'ارفع مرجعًا واضحًا للشخصية وآخر للمنتج، ثم راجع المشاهد والكلام المنطوق. نحافظ على الصوت الأصلي عند التجميع.' : kind === 'image' ? 'ارفع صورة المنتج للحفاظ على تفاصيله. بعد الإنتاج تقدر تختار «تعديل الصورة» من المكتبة.' : 'استخدم سكريبتك أو اكتب النص مباشرة، والملف النهائي يظهر في المكتبة.'}</p>
        <p>المسار الحالي: {kind === 'image' ? IMAGE_MODELS[resolvedModel] : ugc ? 'Seedance 2.5 — Higgsfield' : kind === 'audio' ? 'ElevenLabs v3 — fal' : 'Kling 2.6 + ElevenLabs — fal'}</p>
        {ugc && <p>راجع النطق المصري وتزامن الشفايف وشكل المنتج قبل النشر. كل مشهد يُولَّد بصورة مستقلة بالمراجع نفسها.</p>}
        <p>كل مشهد وصوت وتفريغ طلب مدفوع. التكلفة الفعلية في حساب المزود؛ الإلغاء قد لا يمنع تكلفة مرحلة بدأت.</p>
        <p>حتى {connection?.daily_limit ?? '—'} طلب يوميًا و{connection?.max_active ?? '—'} جاريين لكل عميل.</p>
      </aside>
    </div>
    <section className="space-y-3"><h2 className="text-lg font-semibold text-white">مكتبة الإنتاج</h2>
      {!jobs.length && <p className="text-slate-500 text-sm">ملفات البراند ستظهر هنا بعد أول إنتاج.</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{jobs.map(job => <article key={job.id} className="card p-4 space-y-3">
        <div className="flex gap-2 justify-between"><h3 className="font-medium text-white">{job.title}</h3><span className="chip">{STATES[job.status] || job.status}</span></div>
        {job.asset_id && (job.kind === 'image' ? <img className="w-full max-h-72 object-contain rounded-lg" src={api.assetUrl(job.asset_id)} alt={job.title} /> : job.kind === 'audio' ? <audio className="w-full" controls src={api.assetUrl(job.asset_id)} /> : <video className="w-full max-h-80 rounded-lg" controls src={api.assetUrl(job.asset_id)} />)}
        <p className="text-xs text-slate-500">{job.completed_steps}/{job.total_steps} مراحل مكتملة · {job.providers?.join(' + ')}</p>
        {job.error && <p className="text-xs text-amber-200">{job.error}</p>}
        {job.asset_id && <a className="btn-ghost" href={api.assetUrl(job.asset_id, true)}><Download className="w-4 h-4" />تنزيل الملف</a>}
        {job.kind === 'image' && job.asset_id && !viewer && <button className="btn-ghost" disabled={busy || Boolean(pending.current)} onClick={() => { changeMode('product'); setEditAsset({ id: job.asset_id }); setFile(null); setPrompt(''); setTitle(`تعديل — ${job.title}`); setImageModel(job.image_model || 'default'); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>تعديل الصورة</button>}
        {job.can_finalize && !viewer && <button className="btn-ghost" onClick={() => act(() => api.finalizeProduction(job.id))}>إعادة التجميع بدون توليد مدفوع</button>}
        {ACTIVE.includes(job.status) && !viewer && <button className="btn-ghost" onClick={() => act(() => api.cancelProduction(job.id))}>طلب إلغاء</button>}
      </article>)}</div>
      <div className="flex gap-2"><button className="btn-ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>السابق</button><button className="btn-ghost" disabled={jobs.length < 50} onClick={() => setOffset(offset + 50)}>التالي</button></div>
    </section>
  </div>
}

function Language({ value, onChange }) {
  return <label className="label">لغة الكلام<select className="input mt-1" value={value} onChange={e => onChange(e.target.value)}><option value="ar">العربية — مصري للـUGC</option><option value="en">English</option></select></label>
}
