"""The AI assistant behind the forms.

Onboarding is the friction: a brand plan needs a lot of context before it
produces anything, and typing it all is where people give up. The assistant
removes the typing without removing the substance, because what it may do is
bounded per field by ASSIST_POLICY:

  none    -> a fact only the operator has. The assistant returns no value and
             says what to supply. Inventing revenue or a competitor here would
             produce a plan that analyses fiction.
  extract -> already in the Brand Brain or in a source the operator handed over.
             Pulled through verbatim, never embellished.
  draft   -> judgement and phrasing, proposed from context that already exists.

Every suggestion carries what it was derived from, so the operator can see at a
glance whether it is their own data coming back or the model's proposal.
"""
from __future__ import annotations

import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field as PField

from . import prompting
from .config import settings
from .llm import Usage, client
from .modules import Module
from .skill_engine import registry

log = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]


class Suggestion(BaseModel):
    field: str = PField(description="The field name this answers.")
    value: str = PField(description="The proposed value. Empty when needs_user is true.")
    confidence: Confidence
    basis: str = PField(description="One short Arabic line: what this was derived from.")
    needs_user: bool = PField(
        description="True when this is a fact only the operator has and must type."
    )


class SuggestionSet(BaseModel):
    suggestions: list[Suggestion]


ASSIST_RULES = """\
You are filling in a form inside a brand and marketing dashboard, on behalf of
the operator. Your job is to remove typing, never to remove substance.

You are given the Brand Brain (everything already known about this brand) and
the fields to propose. Each field carries a policy that bounds what you may do:

- **draft** — judgement or phrasing. Propose a concrete, specific draft built
  from the brand context you were given. Write it the way the operator would,
  in their language, not as marketing filler. If the context is too thin to say
  anything specific, set `needs_user: true` rather than writing something vague.

- **extract** — this already exists in the Brand Brain, or in a source the
  operator supplied. Pull it through. If it is genuinely not there, set
  `needs_user: true`. Never approximate it.

- **none** — a fact only the operator has: money, performance figures, real
  customer quotes, their own taste, their own links. You must return
  `needs_user: true` with an empty value, and use `basis` to say precisely what
  to supply and where to find it. Never guess at these, not even plausibly.

Hard rules, in order of importance:
1. **Never invent a number.** No price, revenue, budget, margin, conversion
   rate, follower count or date unless it appears in the context you were given.
2. **Never invent a named competitor, customer quote, review, award or
   partnership.** A fabricated competitor produces a fabricated strategy.
3. A suggestion you are unsure of is `confidence: "low"` and says why in
   `basis`. Low confidence is useful; a confident guess is not.
4. `basis` is always one short Arabic line naming the source — for example
   "من وصف المنتج في الـ Brand Brain" or "اقتراح مبني على المجال، راجعه".
5. Write `value` in the same language as the field's label (Arabic unless the
   label is English). Keep it tight: these are form fields, not essays.
6. Return exactly one entry per requested field, and nothing for fields you
   were not asked about.
"""


def _field_brief(module: Module, names: list[str]) -> str:
    lines = ["# FIELDS TO PROPOSE", ""]
    for field in module.fields:
        if field.name not in names:
            continue
        bits = [f"- **{field.name}** (policy: {field.assist}) — {field.label}"]
        if field.type == "select" and field.options:
            bits.append(f"  - must be exactly one of: {', '.join(field.options)}")
        if field.type == "number":
            bits.append("  - must be a plain number")
        if field.placeholder:
            bits.append(f"  - example of the shape wanted: {field.placeholder}")
        if field.help:
            bits.append(f"  - note: {field.help}")
        lines.extend(bits)
    return "\n".join(lines)


async def suggest(module: Module, brand, names: list[str],
                  current: dict | None = None) -> tuple[list[Suggestion], Usage]:
    """Propose values for the named fields of one module."""
    assistable = [f.name for f in module.fields if f.name in names]
    if not assistable:
        return [], Usage()

    # A field-level suggestion does not need the reference files — SKILL.md
    # alone carries the skill's vocabulary and rules, at a fraction of the cost.
    skill_text = registry.compose(module.skill, []) if module.skill else ""

    already = {k: v for k, v in (current or {}).items()
               if str(v or "").strip() and not k.startswith("_")}
    filled = ""
    if already:
        filled = "\n# ALREADY FILLED BY THE OPERATOR — stay consistent with this\n" + "\n".join(
            f"- {k}: {v}" for k, v in sorted(already.items()))

    system = "\n\n".join(filter(None, [
        skill_text,
        ASSIST_RULES,
        prompting.brand_context(brand),
    ]))
    task = "\n\n".join(filter(None, [
        f"Deliverable this form feeds: **{module.title}** — {module.subtitle}",
        _field_brief(module, assistable),
        filled,
        "Propose one entry per field listed above, honouring each field's policy.",
    ]))

    response = await client().messages.parse(
        model=settings.model_fast,
        max_tokens=4000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": task}],
        output_config={"effort": "medium"},
        output_format=SuggestionSet,
    )

    parsed = response.parsed_output
    wanted = set(assistable)
    out: list[Suggestion] = []
    for item in (parsed.suggestions if parsed else []):
        if item.field not in wanted:
            continue
        # A `none` field is never allowed to come back with a value, whatever
        # the model decided; the policy is enforced here, not requested.
        field = next(f for f in module.fields if f.name == item.field)
        if field.assist == "none":
            item = item.model_copy(update={"value": "", "needs_user": True})
        out.append(item)

    usage = Usage(
        model=settings.model_fast,
        input_tokens=response.usage.input_tokens or 0,
        output_tokens=response.usage.output_tokens or 0,
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
        cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
    )
    return out, usage


# ---------------------------------------------------------------------------
# Brand bootstrap — the big onboarding win
# ---------------------------------------------------------------------------
class ExtractedProduct(BaseModel):
    name: str
    description: str = ""
    usp: str = ""
    price: float | None = None
    currency: str = ""


class ExtractedCompetitor(BaseModel):
    name: str
    messaging: str = ""
    weakness: str = ""


class ExtractedAvatar(BaseModel):
    name: str
    desire: str = ""
    fear: str = ""
    trigger: str = ""
    objections: str = ""


class BrandProfile(BaseModel):
    name: str = PField(default="", description="The brand's own name as the source states it.")
    one_liner: str = ""
    industry: str = ""
    market: str = ""
    dialect: str = ""
    products: list[ExtractedProduct] = []
    competitors: list[ExtractedCompetitor] = []
    avatars: list[ExtractedAvatar] = []
    voc: list[str] = PField(default=[], description="Real customer quotes found in the source, verbatim.")
    gaps: list[str] = PField(default=[], description="What could not be determined and must be supplied.")


BOOTSTRAP_RULES = """\
You are reading a source the operator handed you — their own website copy, or a
description they wrote — and turning it into a structured brand profile that
seeds a strategy dashboard.

This is **extraction**, not creation. Everything you output must be traceable to
the source text.

- Products, prices and currencies: only what the source states. A price you
  cannot see is `null`, never an estimate.
- Competitors: only ones the source names. If it names none, return an empty
  list. Never fill it with well-known brands in the category.
- Customer quotes (`voc`): only real review or testimonial text present in the
  source, copied verbatim. Never write a quote yourself. Empty list if none.
- Avatars: you may infer at most two from who the source is plainly written for,
  and only if that is evident. Say so in `gaps` when they are inferred.
- `dialect`: pick from مصري / سعودي (حجازي) / خليجي/إماراتي / شامي / فصحى /
  English based on the source's own language. Empty if unclear.
- `name`: the brand's own name exactly as the source writes it.
- The source may contain several pages, each under a `### PAGE:` header. Read
  all of them; product pages carry the prices, review pages carry the quotes.
- `gaps`: list, in Arabic, everything important the source did not tell you —
  pricing, margins, real reviews, competitors, performance figures. This list is
  what the operator will go and fill in, so be specific and useful.

An empty field is a correct answer. A plausible invention is not.
"""


async def bootstrap(brand_name: str, source_text: str,
                    source_label: str) -> tuple[BrandProfile, Usage]:
    """Turn a website or a written description into a reviewable Brand Brain.

    Takes a name rather than a Brand row so it can run during onboarding,
    before any brand has been created.
    """
    response = await client().messages.parse(
        model=settings.model_fast,
        max_tokens=8000,
        system=[{"type": "text", "text": BOOTSTRAP_RULES, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": (
            f"Brand name (may be blank — read it off the source): {brand_name or '—'}\n"
            f"Source: {source_label}\n\n"
            f"--- SOURCE TEXT ---\n{source_text[:60000]}\n--- END ---\n\n"
            "Extract the brand profile."
        )}],
        output_config={"effort": "medium"},
        output_format=BrandProfile,
    )

    usage = Usage(
        model=settings.model_fast,
        input_tokens=response.usage.input_tokens or 0,
        output_tokens=response.usage.output_tokens or 0,
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
        cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
    )
    return response.parsed_output or BrandProfile(), usage
