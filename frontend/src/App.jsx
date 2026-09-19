import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Brain, Calculator as CalculatorIcon, ChevronDown, Library as LibraryIcon,
  LogOut, Palette, PenLine, Plus, Settings, Sparkles, TrendingUp,
} from 'lucide-react'
import { moduleIcon } from './icons'
import { api } from './api'
import { Banner, Modal, Spinner } from './components/ui'
import Login from './views/Login'
import ModuleRun from './views/ModuleRun'
import BrandBrain from './views/BrandBrain'
import Library from './views/Library'
import Calculator from './views/Calculator'
import Admin from './views/Admin'

const TABS = [
  { id: 'branding',  label: 'Branding',  icon: Palette,    hint: 'هوية واستراتيچية البراند' },
  { id: 'content',   label: 'Content',   icon: PenLine,    hint: 'كوبي وسكريبتات ومراجعات' },
  { id: 'marketing', label: 'Marketing', icon: TrendingUp, hint: 'خطط ودراسات سوق' },
]

export default function App() {
  const [user, setUser] = useState(undefined)   // undefined = still checking
  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)) }, [])

  if (user === undefined) {
    return <div className="min-h-full grid place-items-center"><Spinner className="w-7 h-7 text-brand-400" /></div>
  }
  if (!user) return <Login onSignedIn={setUser} />
  return <Shell user={user} onSignedOut={() => setUser(null)} />
}

function Shell({ user, onSignedOut }) {
  const [catalog, setCatalog] = useState(null)
  const [clients, setClients] = useState([])
  const [brands, setBrands] = useState([])
  const [brandId, setBrandId] = useState(localStorage.getItem('ecbt.brand') || '')
  const [brand, setBrand] = useState(null)
  const [view, setView] = useState('branding')
  const [moduleKey, setModuleKey] = useState(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  const refreshWorkspace = useCallback(async () => {
    try {
      const [cl, br] = await Promise.all([api.clients(), api.brands()])
      setClients(cl); setBrands(br)
      setBrandId((current) => (br.some((b) => b.id === current) ? current : br[0]?.id || ''))
    } catch (err) { setError(err.message) }
  }, [])

  useEffect(() => { api.catalog().then(setCatalog).catch((e) => setError(e.message)) }, [])
  useEffect(() => { refreshWorkspace() }, [refreshWorkspace])

  const loadBrand = useCallback(async () => {
    if (!brandId) { setBrand(null); return }
    try { setBrand(await api.brand(brandId)) } catch (err) { setError(err.message) }
  }, [brandId])

  useEffect(() => {
    loadBrand()
    if (brandId) localStorage.setItem('ecbt.brand', brandId)
  }, [brandId, loadBrand])

  const modules = catalog?.modules || []
  const activeModule = useMemo(
    () => modules.find((m) => m.key === moduleKey) || null, [modules, moduleKey])

  async function signOut() {
    try { await api.logout() } finally { onSignedOut() }
  }

  const needsBrand = ['branding', 'content', 'marketing', 'brain', 'library'].includes(view)

  return (
    <div className="min-h-full flex flex-col">
      <Header
        user={user} clients={clients} brands={brands} brandId={brandId}
        onBrand={(id) => { setBrandId(id); setModuleKey(null) }}
        onNewBrand={() => setCreating(true)} onSignOut={signOut}
      />

      <Nav view={view} onView={(v) => { setView(v); setModuleKey(null) }} isOwner={user.role === 'owner'} />

      <main className="flex-1 w-full max-w-[1400px] mx-auto px-4 sm:px-6 py-6">
        {error && <div className="mb-4"><Banner kind="error" onClose={() => setError('')}>{error}</Banner></div>}

        {!catalog ? (
          <div className="py-24 grid place-items-center"><Spinner className="w-7 h-7 text-brand-400" /></div>
        ) : needsBrand && !brand ? (
          <EmptyState onCreate={() => setCreating(true)} hasClients={clients.length > 0}
                      isOwner={user.role === 'owner'} />
        ) : activeModule ? (
          <ModuleRun module={activeModule} brand={brand}
                     onBack={() => setModuleKey(null)} onBrainChanged={loadBrand} />
        ) : view === 'brain' ? (
          <BrandBrain brand={brand} onChanged={loadBrand} />
        ) : view === 'library' ? (
          <Library brand={brand} modules={modules} />
        ) : view === 'calculator' ? (
          <Calculator />
        ) : view === 'admin' ? (
          <Admin clients={clients} onClientsChanged={refreshWorkspace} />
        ) : (
          <ModuleGrid tab={view} modules={modules} onPick={setModuleKey} />
        )}
      </main>

      <NewBrandModal open={creating} clients={clients} onClose={() => setCreating(false)}
                     onCreated={async (created) => {
                       setCreating(false); await refreshWorkspace(); setBrandId(created.id)
                     }} />
    </div>
  )
}

function Header({ user, clients, brands, brandId, onBrand, onNewBrand, onSignOut }) {
  const byClient = clients.map((c) => ({ ...c, brands: brands.filter((b) => b.client_id === c.id) }))

  return (
    <header className="sticky top-0 z-30 border-b border-ink-line bg-ink/85 backdrop-blur-xl">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 h-14 flex items-center gap-3">
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-brand-500 grid place-items-center">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="hidden sm:block text-sm font-semibold text-white">C&B Tool</span>
        </div>

        <div className="relative flex-1 max-w-xs">
          <select value={brandId} onChange={(e) => onBrand(e.target.value)}
                  className="input !py-2 appearance-none pe-9 text-sm">
            {!brands.length && <option value="">لا يوجد براند</option>}
            {byClient.map((c) => c.brands.length > 0 && (
              <optgroup key={c.id} label={c.name}>
                {c.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </optgroup>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-slate-600 absolute start-3 top-1/2 -translate-y-1/2
                                  pointer-events-none" />
        </div>

        <button onClick={onNewBrand} className="btn-ghost !px-2.5 !py-2" title="براند جديد">
          <Plus className="w-4 h-4" />
        </button>

        <div className="ms-auto flex items-center gap-2">
          <span className="hidden md:block text-xs text-slate-500">{user.name || user.email}</span>
          <button onClick={onSignOut} className="btn-ghost !px-2.5 !py-2" title="خروج">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  )
}

function Nav({ view, onView, isOwner }) {
  const extras = [
    { id: 'brain', label: 'Brand Brain', icon: Brain },
    { id: 'library', label: 'المكتبة', icon: LibraryIcon },
    { id: 'calculator', label: 'الحاسبة', icon: CalculatorIcon },
    ...(isOwner ? [{ id: 'admin', label: 'الإدارة', icon: Settings }] : []),
  ]

  return (
    <nav className="border-b border-ink-line bg-ink-soft/40">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 flex gap-1 overflow-x-auto">
        {[...TABS, ...extras].map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => onView(id)}
                  className={`flex items-center gap-2 whitespace-nowrap px-3.5 py-3 text-sm
                              border-b-2 transition ${view === id
                    ? 'border-brand-500 text-white'
                    : 'border-transparent text-slate-500 hover:text-slate-300'}`}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>
    </nav>
  )
}

function ModuleGrid({ tab, modules, onPick }) {
  const items = modules.filter((m) => m.tab === tab)
  const meta = TABS.find((t) => t.id === tab)
  const generators = items.filter((m) => m.kind !== 'review')
  const reviews = items.filter((m) => m.kind === 'review')

  return (
    <div className="space-y-7 animate-rise">
      <div>
        <h1 className="text-xl font-bold text-white">{meta?.label}</h1>
        <p className="text-sm text-slate-500 mt-0.5">{meta?.hint}</p>
      </div>

      <Group items={generators} onPick={onPick} />

      {reviews.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-400">المراجعة والتقييم</h2>
          <Group items={reviews} onPick={onPick} accent />
        </div>
      )}
    </div>
  )
}

function Group({ items, onPick, accent }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((m) => {
        const Icon = moduleIcon(m.icon)
        const isCalc = m.kind === 'calculator'
        return (
          <button key={m.key} onClick={() => !isCalc && onPick(m.key)}
                  disabled={isCalc}
                  className={`card p-4 text-start transition group ${isCalc
                    ? 'opacity-60 cursor-default'
                    : 'hover:border-brand-500/40 hover:bg-ink-line/30'}`}>
            <div className="flex items-start gap-3">
              <div className={`w-9 h-9 rounded-xl grid place-items-center shrink-0 transition ${
                accent ? 'bg-amber-500/10 text-amber-300' : 'bg-brand-500/10 text-brand-300'}`}>
                <Icon className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-white">{m.title}</div>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">{m.subtitle}</p>
                <div className="flex flex-wrap gap-1.5 mt-2.5">
                  {m.command && <span className="chip font-mono !text-[10px]">{m.command}</span>}
                  {m.sections?.length > 0 && (
                    <span className="chip !text-[10px]">{m.sections.length} قسم</span>
                  )}
                  {m.tier === 'fast' && <span className="chip !text-[10px]">سريع</span>}
                  {isCalc && <span className="chip !text-[10px]">من تاب الحاسبة</span>}
                </div>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function EmptyState({ onCreate, hasClients, isOwner }) {
  return (
    <div className="py-24 text-center max-w-sm mx-auto space-y-4">
      <Brain className="w-10 h-10 mx-auto text-slate-700" />
      <h2 className="text-lg font-semibold text-white">ابدأ ببراند</h2>
      <p className="text-sm text-slate-500 leading-relaxed">
        {hasClients
          ? 'كل الموديولات بتشتغل على براند. اعمل واحد وجاوب على الأساسيات مرة واحدة بس.'
          : isOwner
            ? 'اعمل عميل الأول من تاب الإدارة، وبعدين ضيف تحته البراندات.'
            : 'مفيش عملاء متاحين لحسابك لسه — كلّم المالك يمنحك صلاحية.'}
      </p>
      {hasClients && <button className="btn-primary" onClick={onCreate}>
        <Plus className="w-4 h-4" /> براند جديد</button>}
    </div>
  )
}

function NewBrandModal({ open, clients, onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', one_liner: '', industry: '', client_id: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (open && clients.length && !form.client_id) setForm((f) => ({ ...f, client_id: clients[0].id }))
  }, [open, clients, form.client_id])

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try { onCreated(await api.createBrand(form)) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <Modal open={open} title="براند جديد" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Banner kind="error">{error}</Banner>}
        <div><label className="label">العميل</label>
          <select className="input" value={form.client_id} onChange={set('client_id')} required>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></div>
        <div><label className="label">اسم البراند *</label>
          <input className="input" required value={form.name} onChange={set('name')} /></div>
        <div><label className="label">بيعمل إيه في سطر</label>
          <input className="input" value={form.one_liner} onChange={set('one_liner')} /></div>
        <div><label className="label">المجال</label>
          <input className="input" value={form.industry} onChange={set('industry')} /></div>
        <button className="btn-primary w-full" disabled={busy}>{busy && <Spinner />} إنشاء</button>
      </form>
    </Modal>
  )
}
