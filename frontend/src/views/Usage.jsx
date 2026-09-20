import { api } from '../api'
import { Banner, Spinner, useAsync } from '../components/ui'

export default function Usage({ brand }) {
  const data = useAsync(() => api.usage(brand.id), [brand.id])
  if (data.error) return <Banner kind="error">{data.error}</Banner>
  if (!data.data) return <Spinner />
  const rows = data.data.items
  const known = rows.reduce((sum, r) => sum + (r.cost_usd || 0), 0)
  const labels = { text_generation: 'توليد نص', production: 'إنتاج وسائط', bootstrap: 'استخراج بيانات', field_assist: 'مساعدة الحقول' }
  return <div className="space-y-5">
    <h1 className="text-xl font-bold text-white">استهلاك البراند</h1>
    <p className="text-sm text-slate-400">آخر 200 عملية مسجلة لهذا البراند. العمليات السابقة لتفعيل السجل غير مدرجة.</p>
    <div className="grid gap-4 sm:grid-cols-3"><div className="card p-5"><p className="label">عمليات معروضة</p><p className="text-2xl text-white">{rows.length}</p></div>
      <div className="card p-5"><p className="label">إجمالي التكلفة التقديرية المتاحة</p><p className="text-2xl text-white">${known.toFixed(4)}</p></div>
      <div className="card p-5"><p className="label">عمليات بتكلفة لدى المزود</p><p className="text-2xl text-white">{rows.filter(r => r.cost_usd == null).length}</p></div></div>
    <Banner kind="warn">{data.data.note} قد لا تصل بيانات تكلفة الطلب إذا انقطع الاتصال بالمزود قبل اكتماله.</Banner>
    <div className="card overflow-x-auto"><table className="w-full text-sm text-start"><thead><tr className="text-slate-400 border-b border-ink-line">{['التاريخ', 'العملية', 'الموديل', 'التكلفة التقديرية'].map(x => <th className="p-3 text-start" key={x}>{x}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i} className="border-b border-ink-line text-slate-300"><td className="p-3 whitespace-nowrap">{new Date(r.created_at).toLocaleString('ar-EG')}</td><td className="p-3">{labels[r.operation] || r.operation}</td><td className="p-3 break-all" dir="ltr">{r.model}</td><td className="p-3 whitespace-nowrap">{r.cost_usd == null ? 'راجع فاتورة المزود' : `$${r.cost_usd.toFixed(4)}`}</td></tr>)}</tbody></table></div>
  </div>
}
