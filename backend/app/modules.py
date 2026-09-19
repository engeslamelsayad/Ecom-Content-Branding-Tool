"""The module catalogue: every card the dashboard offers, across the three tabs.

A module binds a UI form to a skill, the reference files that skill needs for
that job, and the command the skill itself defines. Adding a capability means
adding an entry here -- the strategy lives in the Markdown, not in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BRANDING, CONTENT, MARKETING = "branding", "content", "marketing"

EY = "eyouth-branding-diploma"
CC = "conversion-copywriter"
MP = "marketing-plan"


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str = "text"  # text | textarea | select | number | url | file | multiselect
    required: bool = False
    placeholder: str = ""
    options: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class Module:
    key: str
    tab: str
    title: str
    subtitle: str
    icon: str
    skill: str | None = None
    refs: tuple[str, ...] = ()
    command: str = ""
    tier: str = "deep"  # deep -> Opus, fast -> Sonnet
    effort: str = "high"
    fields: tuple[Field, ...] = ()
    # Where the result is folded back into the Brand Brain.
    writes_core: str = ""
    # A multi-section module streams one section at a time so any single
    # section can be regenerated later without re-running the whole thing.
    sections: tuple[tuple[str, str], ...] = ()
    kind: str = "generate"  # generate | review | calculator | report
    instructions: str = ""


DIALECTS = ("مصري", "سعودي (حجازي)", "خليجي/إماراتي", "شامي", "فصحى", "English")
_dialect = Field("dialect", "اللهجة", "select", options=DIALECTS, help="لهجة الكوبي الموجّه للمستهلك")
_product = Field("product", "المنتج", "select", help="اختَر منتجًا من الـ Brand Brain أو اكتب اسمه")
_notes = Field("notes", "ملاحظات إضافية", "textarea", placeholder="أي سياق إضافي تحب الموديول ياخده في اعتباره")


# ---------------------------------------------------------------------------
# TAB 1 — BRANDING
# ---------------------------------------------------------------------------
BRANDING_MODULES: list[Module] = [
    Module(
        key="brand_discovery", tab=BRANDING, title="Brand Discovery", icon="compass",
        subtitle="استبيان الاكتشاف الكامل + ملف المستخدم رباعي الأعمدة",
        skill=EY, refs=("chapter1-foundations.md", "chapter7-execution.md"),
        command="/discovery", writes_core="discovery",
        fields=(
            Field("gap", "المشكلة اللي بتحلها", "textarea", required=True),
            Field("benchmarks", "براندات بتعجبك (2-3) وليه", "textarea"),
            Field("opposites", "براندات مش عايز تبقى زيها وليه", "textarea"),
            Field("emotion", "الإحساس المطلوب في أول 3 ثواني", "text"),
            _notes,
        ),
    ),
    Module(
        key="brand_heart", tab=BRANDING, title="Brand Heart", icon="heart",
        subtitle="Purpose · Vision · Mission · Goals · Values · 6 Attributes",
        skill=EY, refs=("chapter1-foundations.md", "chapter2-brand-heart.md"),
        command="/heart", writes_core="heart",
        fields=(Field("why", "ليه البراند موجود أبعد من الربح؟", "textarea"), _notes),
    ),
    Module(
        key="verbal_identity", tab=BRANDING, title="Verbal Identity", icon="type",
        subtitle="Naming · Voice Chart · Archetype · Brand Story",
        skill=EY, refs=("chapter3-verbal-identity.md",),
        command="/verbal", writes_core="verbal",
        fields=(
            Field("need_naming", "محتاج اقتراحات أسماء؟", "select", options=("نعم", "لا")),
            _dialect, _notes,
        ),
    ),
    Module(
        key="positioning", tab=BRANDING, title="Positioning", icon="target",
        subtitle="Value Triad · Positioning Matrix · Master Statement · 3 Taglines",
        skill=EY, refs=("chapter4-positioning.md",),
        command="/positioning", writes_core="positioning",
        fields=(Field("price_tier", "الشريحة السعرية", "select",
                      options=("اقتصادي", "متوسط", "بريميوم", "لاكشري")), _notes),
    ),
    Module(
        key="visual_identity", tab=BRANDING, title="Visual Identity", icon="palette",
        subtitle="Stylescape · Logo typology · Typography · Color psychology",
        skill=EY, refs=("chapter5-visual-identity.md",),
        command="/visual", writes_core="visual",
        fields=(Field("constraints", "قيود بصرية (ألوان محجوزة، خطوط، إلخ)", "textarea"), _notes),
    ),
    Module(
        key="touchpoints", tab=BRANDING, title="Touchpoints", icon="map",
        subtitle="دورة التجربة 3 مراحل · PX vs UX · Impact-Ease Matrix",
        skill=EY, refs=("chapter6-touchpoints.md",),
        command="/touchpoints", writes_core="touchpoints",
        fields=(Field("channels", "قنوات البيع والتواصل الحالية", "textarea"), _notes),
    ),
    Module(
        key="brand_architecture", tab=BRANDING, title="Brand Architecture", icon="layers",
        subtitle="نموذج معمارية البراند + خريطة الـ Portfolio",
        skill=EY, refs=("chapter7-execution.md",),
        command="/architecture", writes_core="architecture",
        fields=(Field("portfolio", "المنتجات/الخطوط الحالية والمخططة", "textarea"), _notes),
    ),
    Module(
        key="brand_audit", tab=BRANDING, title="Brand Audit", icon="search-check",
        subtitle="تقييم براند قائم على 3 أبعاد + فجوة الإدراك",
        skill=EY, refs=("chapter1-foundations.md", "chapter7-execution.md"),
        command="/audit",
        fields=(
            Field("materials", "المواد الحالية (لينكات سوشيال، موقع، باكدجينج)", "textarea", required=True),
            Field("intended", "الإدراك اللي انت عايزه", "textarea"),
            Field("actual", "الإدراك الفعلي من العملاء", "textarea"),
            _notes,
        ),
    ),
    Module(
        key="brand_report", tab=BRANDING, title="Brand Strategy Report", icon="file-text",
        subtitle="تقرير استراتيچي كامل يجمع كل مخرجات البراند", kind="report",
        skill=EY, refs=("assets/report-template.md",),
        command="/report", effort="xhigh",
        fields=(Field("audience", "التقرير موجّه لمين؟", "select",
                      options=("فريق داخلي", "عميل", "مستثمر", "وكالة تنفيذ")),),
    ),
]

# ---------------------------------------------------------------------------
# TAB 2 — CONTENT
# ---------------------------------------------------------------------------
_ANGLES = """Produce a Creative & Content Angle Matrix, not a list of taglines.

Deliver 12 distinct angles. For each one give, as a table row plus a short
paragraph beneath it:
  - Angle name and the ONE big idea in a single sentence
  - Awareness stage it targets (1-5, Schwartz) and why that stage
  - Market sophistication level it assumes (1-5)
  - The framework best suited to execute it
  - Lead hook line, written in the target dialect
  - The objection it pre-empts
  - Recommended creative format from the 10 validated formats
  - Priority score 1-10 with a one-line rationale

Cover all five awareness stages; at least two angles must sit in competitive
negative space (a claim nobody in the category is making). Close with a ranked
testing order and say which three to shoot first."""

CONTENT_MODULES: list[Module] = [
    Module(
        key="angle_generator", tab=CONTENT, title="Angle Generator", icon="lightbulb",
        subtitle="12 زاوية إعلانية مختلفة استراتيچيًا × مراحل الوعي الخمسة",
        skill=CC, refs=("frameworks.md", "hooks.md", "creative-formats.md"),
        effort="xhigh", instructions=_ANGLES,
        fields=(_product, _dialect,
                Field("platform", "المنصة", "select", options=("Meta", "TikTok", "Google", "كلهم")),
                _notes),
    ),
    Module(
        key="hooks", tab=CONTENT, title="Hook Engine", icon="zap",
        subtitle="8+ هوك مختلفين هيكليًا من مكتبة 35+ أركيتايب",
        skill=CC, refs=("hooks.md", "questioning-flows.md"), command="/hooks", tier="fast",
        fields=(_product, _dialect,
                Field("platform", "المنصة", "select", options=("Meta", "TikTok", "Google", "كلهم")),
                Field("count", "عدد الهوكات", "number", placeholder="8"), _notes),
    ),
    Module(
        key="ad_script", tab=CONTENT, title="Video Ad Script", icon="clapperboard",
        subtitle="جدول Visual/VO بقاعدة الـ 3 ثواني",
        skill=CC, refs=("questioning-flows.md", "frameworks.md", "hooks.md", "creative-formats.md"),
        command="/script",
        fields=(_product, _dialect,
                Field("duration", "المدة", "select", required=True, options=("15s", "30s", "60s", "VSL")),
                Field("format", "الفورمات", "select", options=(
                    "UGC", "مونتاج/Edit", "موشن جرافيك", "Testimonial", "Before/After", "Founder Story")),
                Field("offer", "العرض والسعر", "text"), _notes),
    ),
    Module(
        key="ugc_script", tab=CONTENT, title="UGC Scripts", icon="smartphone",
        subtitle="سكريبتات UGC بصيغة الكرييتور الطبيعية + بريف التصوير",
        skill=CC, refs=("creative-formats.md", "hooks.md", "questioning-flows.md"),
        command="/script", tier="fast",
        instructions=("Write UGC scripts in a real creator's voice -- first person, "
                      "phone-shot, imperfect and unscripted-sounding. Never brand-voice. "
                      "Produce 3 distinct scripts from different UGC archetypes, each with "
                      "a shot list and a note on what the creator should improvise."),
        fields=(_product, _dialect,
                Field("duration", "المدة", "select", options=("15s", "30s", "45s")),
                Field("creator", "نوع الكرييتور", "text", placeholder="مثال: أم شابة 28 سنة"),
                _notes),
    ),
    Module(
        key="voiceover", tab=CONTENT, title="Voiceover Script", icon="mic",
        subtitle="سكريبت صوتي بعلامات النَفَس والتشديد والوقفات",
        skill=CC, refs=("power-elements.md", "questioning-flows.md"), tier="fast",
        fields=(_product, _dialect,
                Field("duration", "المدة", "select", options=("15s", "30s", "60s")),
                Field("tone", "النبرة", "text", placeholder="دافئة / حازمة / مرحة"), _notes),
    ),
    Module(
        key="landing_copy", tab=CONTENT, title="Landing Page Copy", icon="layout",
        subtitle="صفحة كاملة فوق وتحت الفولد بالتشيك ليست الكاملة",
        skill=CC, refs=("questioning-flows.md", "frameworks.md", "selling-elements.md", "power-elements.md"),
        effort="xhigh",
        fields=(_product, _dialect,
                Field("offer", "العرض والسعر والضمان", "textarea", required=True),
                Field("proof", "الإثباتات المتاحة (ريفيوهات، أرقام، شهادات)", "textarea"), _notes),
    ),
    Module(
        key="ad_copy", tab=CONTENT, title="Ad Copy", icon="megaphone",
        subtitle="Meta / TikTok / Google — نص أساسي + عنوان + وصف منفصلين",
        skill=CC, refs=("questioning-flows.md", "frameworks.md", "hooks.md", "selling-elements.md"),
        tier="fast",
        fields=(_product, _dialect,
                Field("platform", "المنصة", "select", required=True, options=("Meta", "TikTok", "Google")),
                Field("offer", "العرض", "text"), _notes),
    ),
    Module(
        key="email_sms", tab=CONTENT, title="Email & SMS", icon="mail",
        subtitle="Welcome · Abandoned Cart · Post-Purchase · Win-Back · Flash Sale",
        skill=CC, refs=("power-elements.md", "questioning-flows.md", "selling-elements.md"),
        tier="fast",
        fields=(_product, _dialect,
                Field("sequence", "نوع التسلسل", "select", required=True, options=(
                    "Welcome", "Abandoned Cart", "Post-Purchase", "Win-Back", "Flash Sale", "SMS فقط")),
                _notes),
    ),
    Module(
        key="voc_mining", tab=CONTENT, title="VoC Mining", icon="quote",
        subtitle="مصفوفة MECLabs من كلام عملائك الحقيقي",
        skill=CC, refs=("questioning-flows.md", "selling-elements.md"), command="/mine",
        writes_core="voc",
        fields=(_product, _dialect, _notes),
    ),
    Module(
        key="aov_architect", tab=CONTENT, title="AOV Architect", icon="package",
        subtitle="Bundles 3 طبقات + Upsell + Cross-sell + طبقة الإلحاح",
        skill=CC, refs=("selling-elements.md", "power-elements.md"), command="/aov",
        fields=(_product, _dialect,
                Field("catalog", "باقي المنتجات المتاحة للـ cross-sell", "textarea"),
                Field("margin", "هامش الربح التقريبي %", "number"), _notes),
    ),
]

# --- Review modules (vision-backed) ---------------------------------------
_REVIEW_TAIL = """
Structure every review exactly like this:

## 1. الحكم السريع
One paragraph: would this convert, and what is the single biggest leak.

## 2. البطاقة (Scorecard)
A table scoring each criterion 1-10 with a one-line justification, then a
weighted total out of 100.

## 3. الأخطاء مرتّبة بالأولوية
A numbered list, worst first. For each: what is wrong, why it costs
conversions (name the MECLabs variable it damages -- M, V, I, F or A), and the
exact fix. Be specific; never write "improve the copy".

## 4. النسخة المصححة
Rewrite the copy that matters, in the brand's dialect, ready to paste.

## 5. أول 3 تجارب
The three highest-leverage A/B tests, with the metric each one moves.

End with a single JSON object in a ```json fence, and nothing after it:
{"total": <0-100>, "criteria": {"<name>": <0-10>, ...}, "top_fixes": ["...", "..."]}
"""

REVIEW_MODULES: list[Module] = [
    Module(
        key="review_static", tab=CONTENT, title="Static Ad Review", icon="image",
        subtitle="ارفع الإعلان → سكور + أخطاء مرتّبة + نسخة مصححة", kind="review",
        skill=CC, refs=("creative-formats.md", "selling-elements.md", "hooks.md", "power-elements.md"),
        effort="xhigh",
        instructions=(
            "You are auditing a static ad creative. Judge it on: thumb-stop power in "
            "the first instant, hook clarity, value proposition legibility, single "
            "focal point, CTA presence and clarity, proof element, mobile legibility "
            "(text size and contrast at feed scale), brand-voice fit, and platform-"
            "native feel. Look at the image carefully before scoring -- cite what you "
            "actually see, never generic advice." + _REVIEW_TAIL),
        fields=(Field("image", "صورة الإعلان", "file", required=True),
                _product, _dialect,
                Field("platform", "المنصة", "select", options=("Meta", "TikTok", "Google")),
                Field("goal", "هدف الإعلان", "text", placeholder="مبيعات مباشرة / وعي / ريتارجتنج"),
                _notes),
    ),
    Module(
        key="review_landing", tab=CONTENT, title="Landing Page Review", icon="globe",
        subtitle="حط الرابط → لقطة كاملة + تشخيص MECLabs قسم بقسم", kind="review",
        skill=CC, refs=("questioning-flows.md", "frameworks.md", "selling-elements.md", "power-elements.md"),
        effort="xhigh",
        instructions=(
            "You are auditing a live landing page. You receive a full-page screenshot "
            "and the extracted page copy. Walk it section by section, above the fold "
            "first, against the skill's Landing Page checklist. Apply the MECLabs "
            "heuristic explicitly: where is motivation missed, where is the value "
            "proposition unclear, where is friction added, where is anxiety left "
            "unanswered." + _REVIEW_TAIL),
        fields=(Field("url", "رابط الصفحة", "url", required=True),
                _product, _dialect,
                Field("traffic", "مصدر الترافيك", "text", placeholder="Meta cold / TikTok / بحث"),
                _notes),
    ),
    Module(
        key="review_video", tab=CONTENT, title="Video Ad Review", icon="video",
        subtitle="ارفع الفيديو → تحليل الهوك والإيقاع والبنية فريم بفريم", kind="review",
        skill=CC, refs=("hooks.md", "creative-formats.md", "frameworks.md", "selling-elements.md"),
        effort="xhigh",
        instructions=(
            "You are auditing a video ad. You receive frames sampled from it -- densely "
            "across the first three seconds, then at intervals -- each labelled with its "
            "timestamp, plus the script or transcript if supplied. Judge: does the first "
            "frame stop the scroll, is the hook landed inside 3 seconds, does the pacing "
            "hold, is the value proposition shown rather than stated, is there proof, is "
            "the CTA unmissable, and is it platform-native. Reason from the timestamps: "
            "say which second a viewer drops at and why."
            "\n\nYou see sampled frames, not motion or audio -- judge composition, text, "
            "pacing and structure, and say so plainly rather than guessing at "
            "transitions or music." + _REVIEW_TAIL),
        fields=(Field("video", "ملف الفيديو", "file", required=True),
                Field("transcript", "السكريبت أو الترانسكريبت", "textarea",
                      help="اختياري بس بيحسّن التحليل كتير"),
                _product, _dialect,
                Field("platform", "المنصة", "select", options=("Meta", "TikTok", "YouTube")),
                _notes),
    ),
]

# ---------------------------------------------------------------------------
# TAB 3 — MARKETING
# ---------------------------------------------------------------------------
PLAN_SECTIONS: tuple[tuple[str, str], ...] = (
    ("m01_summary", "Module 1 — Introduction & Executive Summary"),
    ("m02_swot", "Module 2 — SWOT Analysis"),
    ("m03_competitors", "Module 3 — Competitor Analysis Matrix"),
    ("m04_value_gap", "Module 4 — Value Gap & Market Opportunity"),
    ("m05_pestel", "Module 5 — PESTEL Analysis"),
    ("m06_porter", "Module 6 — Porter's Five Forces"),
    ("m07_stpd", "Module 7 — STPD Study"),
    ("m08_generic", "Module 8 — Porter's Generic Competitive Strategy"),
    ("m09_plc", "Module 9 — Product Life Cycle Strategy"),
    ("m10_posture", "Module 10 — Competition Market Posture"),
    ("m11_4ps", "Module 11 — 4Ps Marketing Mix"),
    ("m12_media", "Module 12 — Media Plan"),
    ("m13_action", "Module 13 — 90-Day Action Plan + Conclusion"),
)

MARKETING_MODULES: list[Module] = [
    Module(
        key="market_onboarding", tab=MARKETING, title="Market Onboarding", icon="clipboard-list",
        subtitle="البلوكات الأربعة — يقرأ الموجود من الـ Brain ويسأل عن الناقص",
        skill=MP, refs=("frameworks-guide.md",), command="/onboard", writes_core="onboarding",
        tier="fast",
        fields=(
            Field("objective", "المتري الوحيد اللي لازم يتحرك خلال 6-12 شهر", "text", required=True),
            Field("revenue", "متوسط الإيراد الشهري الحالي", "text"),
            Field("aov", "متوسط قيمة الطلب (AOV)", "number"),
            Field("repeat_rate", "نسبة إعادة الشراء %", "number"),
            Field("channels", "قنوات جربتها — إيه اللي نجح وإيه اللي فشل", "textarea"),
            _notes,
        ),
    ),
    Module(
        key="full_plan", tab=MARKETING, title="Full Marketing Plan", icon="book-open",
        subtitle="الخطة الاستراتيچية الكاملة — 13 موديول بالتسلسل",
        skill=MP, refs=("frameworks-guide.md", "kpi-benchmarks.md"), command="/buildplan",
        effort="xhigh", sections=PLAN_SECTIONS, writes_core="plan",
        fields=(_dialect,
                Field("objective", "الهدف الأساسي من الخطة", "textarea", required=True),
                Field("budget", "الميزانية الشهرية المتاحة للإعلانات", "text"),
                Field("markets", "الأسواق المستهدفة", "text", placeholder="مصر، السعودية"),
                _notes),
    ),
    Module(
        key="stpd", tab=MARKETING, title="STPD Study", icon="crosshair",
        subtitle="Segmentation · Targeting · Positioning · Differentiation",
        skill=MP, refs=("frameworks-guide.md", "kpi-benchmarks.md"), effort="xhigh",
        writes_core="stpd",
        instructions=("Deliver Module 7 — STPD Study in full, exactly to the skill's "
                      "spec: minimum 3 segmentation cohorts as a table, 2 fully built "
                      "avatars, the master positioning statement, a 2x2 price-"
                      "performance grid with competitors plotted, and a named "
                      "Proprietary Mechanism. Nothing abbreviated."),
        fields=(_product, _dialect,
                Field("markets", "الأسواق المستهدفة", "text"), _notes),
    ),
    Module(
        key="competitor_matrix", tab=MARKETING, title="Competitor Matrix", icon="users",
        subtitle="مصفوفة تنافسية كاملة + منطق كل منافس والفجوات المفتوحة",
        skill=MP, refs=("frameworks-guide.md",), tier="fast",
        instructions="Deliver Module 3 — Competitor Analysis Matrix in full.",
        fields=(Field("competitors", "المنافسين (اسم + أي معلومة عندك)", "textarea", required=True),
                _notes),
    ),
    Module(
        key="swot", tab=MARKETING, title="SWOT + Cross-Strategy", icon="grid",
        subtitle="5 نقاط لكل ربع + استراتيچيات SO/WO/ST/WT",
        skill=MP, refs=("frameworks-guide.md",), tier="fast",
        instructions="Deliver Module 2 — SWOT Analysis in full, including the four cross strategies.",
        fields=(_notes,),
    ),
    Module(
        key="market_forces", tab=MARKETING, title="PESTEL + Porter", icon="wind",
        subtitle="قوى السوق الخارجية + الخمس قوى بدرجات وأدلة",
        skill=MP, refs=("frameworks-guide.md", "kpi-benchmarks.md"),
        instructions=("Deliver Module 5 — PESTEL Analysis and Module 6 — Porter's Five "
                      "Forces, both in full, with the Industry Attractiveness Score."),
        fields=(Field("markets", "الأسواق", "text", required=True), _notes),
    ),
    Module(
        key="media_plan", tab=MARKETING, title="Media Plan", icon="pie-chart",
        subtitle="توزيع القمع + اقتصاديات الوحدة + 3 مستويات ميزانية",
        skill=MP, refs=("frameworks-guide.md", "kpi-benchmarks.md"), effort="xhigh",
        instructions=("Deliver Module 12 — Media Plan in full. Where the user supplied "
                      "unit economics, use those exact figures and do not re-derive them."),
        fields=(Field("budget", "الميزانية الشهرية", "text", required=True),
                Field("markets", "الأسواق", "text"),
                Field("platforms", "المنصات المتاحة", "text", placeholder="Meta, TikTok, Google"),
                _notes),
    ),
    Module(
        key="action_plan_90", tab=MARKETING, title="90-Day Action Plan", icon="calendar",
        subtitle="خطة أسبوع بأسبوع + معمارية الاستهداف + 10 فورمات للاختبار",
        skill=MP, refs=("frameworks-guide.md", "kpi-benchmarks.md"), effort="xhigh",
        instructions="Deliver Module 13 — 90-Day Action Plan in full, including the 10 creative formats.",
        fields=(_dialect, Field("budget", "الميزانية الشهرية", "text"),
                Field("team", "الفريق المتاح", "text", placeholder="مصمم، ميديا باير، كرييتور"),
                _notes),
    ),
    Module(
        key="unit_economics", tab=MARKETING, title="Unit Economics", icon="calculator",
        subtitle="CAC Ceiling · LTV · ROAS · Payback — حساب حقيقي مش تقديري",
        kind="calculator",
    ),
]

ALL_MODULES: list[Module] = (
    BRANDING_MODULES + CONTENT_MODULES + REVIEW_MODULES + MARKETING_MODULES
)
MODULES_BY_KEY: dict[str, Module] = {m.key: m for m in ALL_MODULES}


def get_module(key: str) -> Module:
    if key not in MODULES_BY_KEY:
        raise KeyError(f"unknown module: {key}")
    return MODULES_BY_KEY[key]
