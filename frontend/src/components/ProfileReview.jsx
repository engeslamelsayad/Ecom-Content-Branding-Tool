import { AlertTriangle } from 'lucide-react'
import { Banner } from './ui'

const GROUPS = [
  ['products', 'المنتجات'],
  ['competitors', 'المنافسون'],
  ['avatars', 'الأفاتارات'],
  ['voc', 'كلام العملاء'],
]

export const startAllKept = (profile) => {
  const marks = {}
  for (const [group] of GROUPS) {
    (profile?.[group] || []).forEach((_, i) => { marks[`${group}:${i}`] = true })
  }
  return marks
}

export const applyKept = (profile, keep) => {
  const out = { ...profile }
  for (const [group] of GROUPS) {
    out[group] = (profile[group] || []).filter((_, i) => keep[`${group}:${i}`])
  }
  return out
}

const describe = (group, item) => {
  if (group === 'voc') return `"${item}"`
  const rest = Object.entries(item)
    .filter(([k, v]) => k !== 'name' && v !== null && v !== '')
    .map(([, v]) => v)
    .join(' · ')
  return rest ? `${item.name} — ${rest}` : item.name
}

/**
 * What the extractor found, for the operator to prune before anything is saved.
 *
 * The gaps panel is the honest half: it names what the source did not say, so
 * nobody mistakes a thin profile for a complete one.
 */
export default function ProfileReview({ profile, keep, onToggle, cost, pages }) {
  if (!profile) return null

  return (
    <div className="space-y-4">
      <Banner kind="info">
        دي بيانات مستخرجة من المصدر بس — شيل الغلط قبل الحفظ.
        <span className="text-slate-400">
          {pages ? ` (قرا ${pages} صفحة` : ' ('}
          {cost != null ? `${pages ? ' · ' : ''}كلّف $${Number(cost).toFixed(4)}` : ''})
        </span>
      </Banner>

      <div className="grid gap-2 sm:grid-cols-2">
        {[['name', 'الاسم'], ['one_liner', 'وصف في سطر'],
          ['industry', 'المجال'], ['market', 'السوق'], ['dialect', 'اللهجة']]
          .map(([key, label]) => profile[key] && (
            <div key={key} className="rounded-lg border border-ink-line bg-ink px-3 py-2">
              <div className="text-[10px] text-slate-600">{label}</div>
              <div className="text-xs text-slate-200">{profile[key]}</div>
            </div>
          ))}
      </div>

      {GROUPS.map(([group, title]) => {
        const items = profile[group] || []
        if (!items.length) return null
        return (
          <div key={group}>
            <h3 className="text-xs font-semibold text-slate-400 mb-1.5">
              {title} <span className="text-slate-600">({items.length})</span>
            </h3>
            <div className="space-y-1.5">
              {items.map((item, i) => (
                <label key={i} className="flex items-start gap-2.5 rounded-lg border border-ink-line
                                          bg-ink px-3 py-2 cursor-pointer hover:border-brand-500/30">
                  <input type="checkbox" className="mt-0.5 accent-brand-500"
                         checked={!!keep[`${group}:${i}`]}
                         onChange={() => onToggle(`${group}:${i}`)} />
                  <span className="text-xs text-slate-300 flex-1">{describe(group, item)}</span>
                </label>
              ))}
            </div>
          </div>
        )
      })}

      {(profile.gaps || []).length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/[.07] p-3.5">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold text-amber-200 mb-2">
            <AlertTriangle className="w-3.5 h-3.5" /> الناقص — ده اللي لازم تحطه بنفسك
          </h3>
          <ul className="space-y-1 text-[11px] text-amber-100/80 list-disc ps-4">
            {profile.gaps.map((gap, i) => <li key={i}>{gap}</li>)}
          </ul>
          <p className="mt-2 text-[10px] text-amber-200/60">
            الأداة مابتخترعش الأرقام والمنافسين والريفيوهات — من غيرهم المخرجات هتبقى عامة.
          </p>
        </div>
      )}
    </div>
  )
}
