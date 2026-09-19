import { useState } from 'react'
import { Plus, Shield, Trash2, UserPlus } from 'lucide-react'
import { api } from '../api'
import { Banner, Modal, Spinner, useAsync } from '../components/ui'

export default function Admin({ clients, onClientsChanged }) {
  const users = useAsync(() => api.users(), [])
  const [inviting, setInviting] = useState(false)
  const [managing, setManaging] = useState(null)
  const [error, setError] = useState('')

  async function remove(user) {
    if (!confirm(`مسح ${user.email} نهائيًا؟`)) return
    try { await api.deleteUser(user.id); users.reload() }
    catch (err) { setError(err.message) }
  }

  return (
    <div className="space-y-6">
      {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}

      <Clients clients={clients} onChanged={onClientsChanged} onError={setError} />

      <section className="card">
        <header className="flex items-center justify-between border-b border-ink-line px-5 py-3.5">
          <h2 className="font-semibold text-white flex items-center gap-2">
            <Shield className="w-4 h-4 text-brand-400" /> المستخدمون
          </h2>
          <button className="btn-primary !py-2 !px-3 text-xs" onClick={() => setInviting(true)}>
            <UserPlus className="w-3.5 h-3.5" /> مستخدم جديد
          </button>
        </header>

        <div className="p-5">
          {users.loading ? <Spinner /> : (
            <div className="space-y-2">
              {users.data?.map((u) => (
                <div key={u.id}
                     className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-line
                                bg-ink px-4 py-3">
                  <div className="flex-1 min-w-[180px]">
                    <div className="text-sm text-white">{u.name || u.email}</div>
                    <div className="text-xs text-slate-500" dir="ltr">{u.email}</div>
                  </div>
                  <span className="chip">{u.role}</span>
                  {!u.is_active && <span className="chip !text-rose-300">موقوف</span>}
                  {u.role !== 'owner' && (
                    <>
                      <button className="btn-ghost !py-1.5 !px-2.5 text-xs"
                              onClick={() => setManaging(u)}>الصلاحيات</button>
                      <button className="btn-danger !py-1.5 !px-2.5 text-xs" onClick={() => remove(u)}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <InviteModal open={inviting} onClose={() => setInviting(false)}
                   onDone={() => { setInviting(false); users.reload() }} />
      <AccessModal user={managing} clients={clients} onClose={() => setManaging(null)} />
    </div>
  )
}

function Clients({ clients, onChanged, onError }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function add(e) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try { await api.createClient({ name: name.trim() }); setName(''); onChanged() }
    catch (err) { onError(err.message) }
    finally { setBusy(false) }
  }

  async function remove(client) {
    if (!confirm(`مسح "${client.name}" وكل البراندات اللي تحته؟`)) return
    try { await api.deleteClient(client.id); onChanged() }
    catch (err) { onError(err.message) }
  }

  return (
    <section className="card">
      <header className="border-b border-ink-line px-5 py-3.5">
        <h2 className="font-semibold text-white">العملاء</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          كل عميل معزول — المستخدم بيشوف العملاء اللي اتمنحله صلاحية عليهم بس.
        </p>
      </header>

      <div className="p-5 space-y-4">
        <form onSubmit={add} className="flex gap-2">
          <input className="input flex-1" placeholder="اسم العميل الجديد"
                 value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-primary shrink-0" disabled={busy || !name.trim()}>
            {busy ? <Spinner /> : <Plus className="w-4 h-4" />} إضافة
          </button>
        </form>

        <div className="flex flex-wrap gap-2">
          {clients.map((c) => (
            <span key={c.id} className="chip !text-slate-300 !py-1.5">
              {c.name}
              <button onClick={() => remove(c)} className="text-slate-600 hover:text-rose-400">
                <Trash2 className="w-3 h-3" />
              </button>
            </span>
          ))}
          {!clients.length && <p className="text-sm text-slate-500">مفيش عملاء لسه.</p>}
        </div>
      </div>
    </section>
  )
}

function InviteModal({ open, onClose, onDone }) {
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'member' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try { await api.createUser(form); setForm({ email: '', name: '', password: '', role: 'member' }); onDone() }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <Modal open={open} title="مستخدم جديد" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Banner kind="error">{error}</Banner>}
        <div><label className="label">الاسم</label>
          <input className="input" value={form.name} onChange={set('name')} /></div>
        <div><label className="label">الإيميل *</label>
          <input className="input text-start" dir="ltr" type="email" required
                 value={form.email} onChange={set('email')} /></div>
        <div><label className="label">الباسورد * (8 حروف على الأقل)</label>
          <input className="input text-start" dir="ltr" type="text" required minLength={8}
                 value={form.password} onChange={set('password')} /></div>
        <div><label className="label">الدور</label>
          <select className="input" value={form.role} onChange={set('role')}>
            <option value="member">عضو — بيشوف العملاء المصرّح له بيهم بس</option>
            <option value="owner">مالك — صلاحية كاملة على كل حاجة</option>
          </select></div>
        <button className="btn-primary w-full" disabled={busy}>{busy && <Spinner />} إنشاء</button>
      </form>
    </Modal>
  )
}

function AccessModal({ user, clients, onClose }) {
  const grants = useAsync(() => (user ? api.memberships(user.id) : Promise.resolve([])), [user?.id])
  if (!user) return null

  const byClient = Object.fromEntries((grants.data || []).map((g) => [g.client_id, g.role]))

  async function change(clientId, role) {
    if (role === 'none') await api.revoke(user.id, clientId)
    else await api.grant({ user_id: user.id, client_id: clientId, role })
    grants.reload()
  }

  return (
    <Modal open title={`صلاحيات ${user.name || user.email}`} onClose={onClose}>
      {grants.loading ? <Spinner /> : (
        <div className="space-y-2">
          {clients.map((c) => (
            <div key={c.id} className="flex items-center gap-3 rounded-xl border border-ink-line
                                       bg-ink px-4 py-2.5">
              <span className="flex-1 text-sm text-slate-200">{c.name}</span>
              <select className="input !w-auto !py-1.5 text-xs"
                      value={byClient[c.id] || 'none'}
                      onChange={(e) => change(c.id, e.target.value)}>
                <option value="none">لا شيء</option>
                <option value="viewer">قراءة فقط</option>
                <option value="editor">تشغيل وتعديل</option>
                <option value="admin">إدارة كاملة</option>
              </select>
            </div>
          ))}
          {!clients.length && <p className="text-sm text-slate-500">اعمل عميل الأول.</p>}
        </div>
      )}
    </Modal>
  )
}
