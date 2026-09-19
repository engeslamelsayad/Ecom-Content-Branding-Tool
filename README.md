# Ecom Content & Branding Tool

لوحة تحكم متكاملة لمخرجات الـ **Branding** والـ **Content** والـ **Marketing** للتجارة الإلكترونية،
مبنية فوق ثلاث Agent Skills موجودة في نفس الريبو.

> **المبدأ الأساسي:** الـ skills هي مصدر الحقيقة الوحيد. الأداة بتقراها من الملفات وقت التشغيل —
> تعدّل ملف Markdown، تعمل redeploy، الأداة بقت أذكى. من غير ما تلمس سطر كود.

---

## المحتويات

| الفولدر | الدور |
|---|---|
| `eyouth-branding-diploma/` | استراتيچية البراند — 7 فصول، 9 أوامر |
| `conversion-copywriter/` | كتابة إعلانات تحويلية — 25+ framework، 35+ hook |
| `marketing-plan/` | خطط تسويقية ودراسات سوق — 13 موديول |
| `backend/` | FastAPI — محرك الـ skills، الـ Brand Brain، البث، التصدير |
| `frontend/` | React + Vite — الداشبورد |

---

## الأفكار المعمارية

### 1. Brand Brain — ذاكرة دائمة لكل براند
الـ skills مكتوبة للشات، وبتصرّ على استبيان قبل أي مخرج. في داشبورد ده كان هيخلّيك
تجاوب على نفس الأسئلة كل مرة. فالأداة بتخزّن سياق البراند مرة واحدة:

```
Brand ──┬── Identity      (الاسم · المجال · السوق · اللهجة)
        ├── Products      (السعر · التكلفة · الـ USP)
        ├── Avatars       (الرغبة · الخوف · الـ Trigger · الاعتراضات)
        ├── Competitors   (الرسالة · السعر · نقطة الضعف)
        ├── VoC Bank      (كلام عملاء حقيقي، بيتحط في الكوبي بالحرف)
        └── Core          (مخرجات الموديولات السابقة)
```

كل موديول بيقرأ من الـ Brain، و**بيكتب فيه**: تعمل `/heart` فالقيم والأركيتايب يتخزنوا،
وأي موديول بعده يطلع متسق معاهم أوتوماتيك.

### 2. Progressive disclosure + prompt caching
الـ skills حوالي 3,700 سطر. كل موديول بيحمّل الـ `SKILL.md` بتاعه + الـ references
اللي محتاجها بس. والبرومبت مرتّب عشان الكاش:

```
system[0] = نص الـ skill      ← ثابت لكل موديول  (cached)
system[1] = قواعد + Brand Brain ← ثابت لكل براند   (cached)
messages  = الطلب نفسه          ← متغيّر، مش متكاش
```

### 3. الحسابات بكود، مش بموديل
الـ LLM بيغلط في الحساب. سقف الـ CAC والـ LTV و ROAS التعادل وتسعير الـ bundles
بتتحسب في `backend/app/calculators.py` والموديل **بيفسّر** النتيجة بس.

### 4. الموديل الهجين
- **Opus 5** — الشغل الاستراتيچي العميق والمراجعات
- **Sonnet 5** — الهوكات وتنويعات الكوبي والمخرجات السريعة

تقدر تعمل override يدوي في أي تشغيلة.

---

## التابات

### 🎨 Branding (9 موديولات)
Discovery · Brand Heart · Verbal Identity · Positioning · Visual Identity ·
Touchpoints · Architecture · Audit · Report

### ✍️ Content (13 موديول)
**توليد:** Angle Generator · Hooks · Ad Script · UGC Scripts · Voiceover ·
Landing Copy · Ad Copy · Email & SMS · VoC Mining · AOV Architect
**مراجعة:** Static Ad · Landing Page · Video Ad

### 📊 Marketing (9 موديولات)
Onboarding · Full Plan (13 قسم) · STPD · Competitor Matrix · SWOT ·
PESTEL + Porter · Media Plan · 90-Day Plan · Unit Economics

---

## محرك المراجعة

| النوع | الطريقة | القيد |
|---|---|---|
| **Static Ad** | رفع الصورة → تصغير → تحليل بصري | — |
| **Landing Page** | الرابط → Chromium يفتحها بعرض موبايل → لقطة كاملة مقسّمة + استخراج النص | الصفحات اللي محتاجة تسجيل دخول |
| **Video Ad** | رفع الفيديو → `ffmpeg` يستخرج فريمات (مكثفة في أول 3 ثواني) + الترانسكريبت | **فريمات مش حركة** — بيقيّم الهوك والبنية والإيقاع، مش الموسيقى ولا الـ transitions |

كل مراجعة بتطلع سكور من 100 + أخطاء مرتّبة بالأولوية + نسخة مصححة، وبتخزّن
البطاقة كـ JSON عشان تقدر تتابع التحسّن مع الوقت.

---

## التشغيل محليًا

```bash
# الباك إند
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
playwright install chromium          # لمراجعة الـ landing pages
cp .env.example .env                 # وحط الـ ANTHROPIC_API_KEY
cd backend && uvicorn app.main:app --reload

# الفرونت إند (تيرمنال تاني)
cd frontend && npm install && npm run dev
```

الواجهة على `http://localhost:5173`، والـ API على `http://localhost:8000`.
أول تسجيل دخول بالـ `ADMIN_EMAIL` و `ADMIN_PASSWORD` من ملف `.env`.

يحتاج `ffmpeg` مثبّت على الجهاز لمراجعة الفيديو.

---

## النشر على Railway

1. **اربط الريبو** بمشروع Railway جديد — هيلاقي الـ `Dockerfile` لوحده.
2. **ضيف Postgres** من `+ New → Database → PostgreSQL`.
3. **ضيف Volume** على الخدمة، ومسار الـ mount `/data`
   — من غيره الصور والفيديوهات المرفوعة بتتمسح مع كل deploy.
4. **حط الـ Variables:**

| المتغير | القيمة |
|---|---|
| `ANTHROPIC_API_KEY` | مفتاحك |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `STORAGE_DIR` | `/data/storage` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | بيانات أول دخول |

5. **Deploy** — الـ healthcheck على `/api/health`.

> **خدمة واحدة بـ worker واحد** بالتصميم: بَفَر البث المباشر عايش في ذاكرة العملية.
> التشغيلة نفسها متخزّنة في قاعدة البيانات، فلو العملية اترستارت المخرج مش بيضيع —
> بس التدفق الحي للتشغيلات الجارية وقتها بيتقطع.

---

## ملاحظات تشغيلية

- **التكلفة:** تشغيلة `/buildplan` كاملة (13 موديول) بتوصل $1.5–4 حسب الموديل.
  الكاش بيقلّلها كتير في التشغيلات المتتالية على نفس البراند. عدّاد التكلفة ظاهر في كل تشغيلة.
- **البنشماركات** في `marketing-plan/references/kpi-benchmarks.md` بتاريخ 2024–2025 —
  حدّثها دوريًا، هي ملف Markdown عادي.
- **بنك الـ VoC:** الـ skill بيحاكي كلام العملاء لو البنك فاضي. حطّ ريفيوهات حقيقية
  وهتلاقي فرق كبير في جودة الكوبي.
- **عزل العملاء:** المستخدم بيوصل للبراند عن طريق `Membership` على العميل بس.
  المالك (`owner`) بس اللي بيشوف كل حاجة ويدير المستخدمين.
- **تعديل الـ skills:** عدّل الـ Markdown و `POST /api/skills/reload`، أو اعمل redeploy.
