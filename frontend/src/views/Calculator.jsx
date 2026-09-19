import { useState } from 'react'
import { Calculator as CalcIcon, TrendingUp } from 'lucide-react'
import { api } from '../api'
import { Banner, Spinner } from '../components/ui'

const INPUTS = [
  ['aov', 'متوسط قيمة الطلب (AOV)', 850],
  ['cogs', 'تكلفة البضاعة للطلب', 300],
  ['shipping_cost', 'تكلفة الشحن اللي بتتحملها', 60],
  ['payment_fee_pct', 'رسوم الدفع / التحصيل %', 2.5],
  ['return_rate_pct', 'نسبة المرتجع %', 12],
  ['purchases_per_year', 'عدد مرات الشراء في السنة', 2],
  ['lifespan_years', 'عمر العميل بالسنين', 1.5],
  ['target_ltv_cac', 'نسبة LTV:CAC المستهدفة', 3],
  ['current_cac', 'الـ CAC الحالي (لو معروف)', 210],
]

/** Real arithmetic, computed server-side — never asked of the model. */
export default function Calculator() {
  const [form, setForm] = useState(Object.fromEntries(INPUTS.map(([k, , v]) => [k, v])))
  const [currency, setCurrency] = useState('EGP')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setBusy(true); setError('')
    try {
      setResult(await api.economics({
        ...Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v) || 0])),
        currency,
      }))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const fmt = (n) => (n == null ? '—' : `${Number(n).toLocaleString('en-US',
    { maximumFractionDigits: 2 })} ${currency}`)

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] items-start">
      <section className="card p-5 space-y-4">
        <h2 className="font-semibold text-white flex items-center gap-2">
          <CalcIcon className="w-4 h-4 text-brand-400" /> اقتصاديات الوحدة
        </h2>
        {error && <Banner kind="error">{error}</Banner>}

        <div>
          <label className="label">العملة</label>
          <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {['EGP', 'SAR', 'AED', 'USD'].map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {INPUTS.map(([key, label]) => (
            <div key={key}>
              <label className="label">{label}</label>
              <input className="input" type="number" step="any" value={form[key]}
                     onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </div>
          ))}
        </div>

        <button className="btn-primary w-full" onClick={run} disabled={busy}>
          {busy && <Spinner />} احسب
        </button>
      </section>

      <section className="card p-5 min-h-[320px]">
        {!result ? (
          <div className="h-full grid place-items-center text-center">
            <div className="max-w-xs space-y-2">
              <TrendingUp className="w-7 h-7 mx-auto text-slate-700" />
              <p className="text-sm text-slate-500">
                الأرقام دي بتتحسب بكود حقيقي، مش بتتسأل للموديل.
              </p>
              <p className="text-[11px] text-slate-600">
                الـ Media Plan بياخد النتيجة دي كما هي بدل ما يقدّرها.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <Banner kind={result.contribution_per_order <= 0 ? 'error'
                         : (result.current_ltv_cac ?? 9) >= result.target_roas / result.breakeven_roas
                           ? 'success' : 'warn'}>
              {result.verdict}
            </Banner>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Stat label="هامش الربح الإجمالي" value={`${result.gross_margin_pct}%`} />
              <Stat label="مساهمة الطلب الواحد" value={fmt(result.contribution_per_order)} />
              <Stat label="هامش المساهمة" value={`${result.contribution_margin_pct}%`} />
              <Stat label="قيمة العميل (LTV)" value={fmt(result.ltv)} />
              <Stat label="سقف الـ CAC" value={fmt(result.cac_ceiling)} highlight />
              <Stat label="أقصى CPA لأول طلب" value={fmt(result.max_cpa_first_order)} />
              <Stat label="ROAS التعادل" value={`${result.breakeven_roas}×`} highlight />
              <Stat label="ROAS المستهدف" value={`${result.target_roas}×`} />
              <Stat label="LTV:CAC الحالي"
                    value={result.current_ltv_cac ? `${result.current_ltv_cac}:1` : '—'} />
            </div>

            <div className="rounded-xl border border-ink-line bg-ink p-4 text-xs text-slate-400
                            leading-relaxed space-y-1.5">
              <p>
                <span className="text-slate-300">سقف الـ CAC ({fmt(result.cac_ceiling)})</span> محسوب
                من قيمة العميل الكاملة مقسومة على النسبة المستهدفة.
              </p>
              <p>
                معادلة الـ skill المبسّطة (AOV × هامش ÷ النسبة) بتدي{' '}
                <span className="text-slate-300">{fmt(result.cac_ceiling_skill_formula)}</span> —
                أقل، لأنها بتحسب أول طلب بس من غير تكرار الشراء.
              </p>
              <p>
                تحت الـ <span className="text-slate-300">{result.breakeven_roas}×</span> انت بتخسر
                على كل جنيه إعلان.
              </p>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value, highlight }) {
  return (
    <div className={`rounded-xl border p-3.5 ${highlight
      ? 'border-brand-500/40 bg-brand-500/[.07]' : 'border-ink-line bg-ink'}`}>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${
        highlight ? 'text-brand-200' : 'text-white'}`}>{value}</div>
    </div>
  )
}
