import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { api } from '../api'
import { Banner, Spinner } from '../components/ui'

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      onSignedIn(await api.login(email.trim(), password))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full grid place-items-center px-4 py-10">
      <div className="w-full max-w-sm animate-rise">
        <div className="text-center mb-7">
          <div className="inline-flex w-12 h-12 items-center justify-center rounded-2xl
                          bg-brand-500 shadow-lg shadow-brand-500/30 mb-4">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">Content & Branding Tool</h1>
          <p className="text-sm text-slate-500 mt-1.5">
            Branding · Content · Marketing — في مكان واحد
          </p>
        </div>

        <form onSubmit={submit} className="card p-6 space-y-4">
          {error && <Banner kind="error">{error}</Banner>}

          <div>
            <label className="label" htmlFor="email">الإيميل</label>
            <input id="email" type="email" required autoComplete="username" dir="ltr"
                   className="input text-start" value={email}
                   onChange={(e) => setEmail(e.target.value)} />
          </div>

          <div>
            <label className="label" htmlFor="password">الباسورد</label>
            <input id="password" type="password" required autoComplete="current-password" dir="ltr"
                   className="input text-start" value={password}
                   onChange={(e) => setPassword(e.target.value)} />
          </div>

          <button className="btn-primary w-full" disabled={busy}>
            {busy && <Spinner />} دخول
          </button>
        </form>
      </div>
    </div>
  )
}
