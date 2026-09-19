"""Turns a Brand Brain plus a filled form into the prompt a skill expects.

The skills were written for a chat, where they interrogate the user before
writing. A dashboard collects that same information as a form and as stored
brand state, so the operating rules below re-point the skill at supplied data
instead of letting it open with a questionnaire -- while keeping its hard
rule that nothing may be invented to fill a gap.
"""
from __future__ import annotations

import json
from typing import Any

from .modules import Module

DIALECT_MAP = {
    "مصري": "Egyptian Arabic (Masri)",
    "سعودي (حجازي)": "Saudi Arabic (Hejazi)",
    "خليجي/إماراتي": "Gulf / Emirati Arabic",
    "شامي": "Levantine Arabic",
    "فصحى": "Modern Standard Arabic",
    "English": "English",
}

OPERATING_RULES = """\
# HOW THIS SKILL IS BEING RUN

You are running inside a dashboard, not a chat. Follow the skill above in
full, with these adaptations:

1. **The intake is already answered.** Everything the skill would normally ask
   for is supplied below, under BRAND BRAIN and REQUEST. Treat it as the
   completed questionnaire. Do not re-ask it and do not open with questions.
2. **Never invent missing facts.** Where something the skill needs is genuinely
   absent, say so explicitly in a short block titled `> ⚠️ افتراضات ومعلومات ناقصة`,
   state the assumption you are proceeding on, and carry on. Never silently
   fabricate a number, a competitor, a review or a result.
3. **Produce the deliverable, whole.** No preamble, no "here is what I will
   do", no offer to continue. Open directly with the output. Never truncate a
   module or replace a section with a summary.
4. **Markdown that survives export.** Real headings, real tables, real lists.
   No HTML. Keep tables narrow enough to read on a phone.
5. **Arabic is the default.** Consumer-facing copy goes in the dialect named
   below, exactly. Strategic analysis and framework labels stay in Arabic with
   the English technical terms kept as-is (Positioning, CAC, Hook, ...). Never
   mix two dialects in one piece of copy.
6. **Every claim earns its place.** Ground it in the supplied data, the
   framework's own logic, or a stated assumption. No filler, no platitudes.
7. **Close with the bridge.** End every strategic deliverable with a short
   `## الجسر التنفيذي` — how this converts into an ad angle, which objection it
   kills, and the single next action.
"""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def brand_context(brand: Any, extras: dict[str, Any] | None = None) -> str:
    """Serialise the Brand Brain.

    Key ordering is fixed so the string stays byte-stable between runs; an
    unstable context block would defeat prompt caching.
    """
    lines: list[str] = ["# BRAND BRAIN", ""]

    lines += [
        "## Identity",
        f"- Brand: {brand.name}",
        f"- One-liner: {brand.one_liner or '—'}",
        f"- Industry: {brand.industry or '—'}",
        f"- Market: {brand.market or '—'}",
        f"- Stage: {brand.stage or '—'}",
        f"- Default dialect: {DIALECT_MAP.get(brand.dialect, brand.dialect)}",
        "",
    ]

    if products := getattr(brand, "products", None):
        lines.append("## Products")
        for p in products:
            price = f"{p.price:g} {p.currency}" if p.price is not None else "—"
            margin = "—"
            if p.price and p.cost is not None and p.price > 0:
                margin = f"{(p.price - p.cost) / p.price * 100:.0f}%"
            lines.append(f"- **{p.name}** | price {price} | gross margin {margin}")
            if p.usp:
                lines.append(f"  - USP: {p.usp}")
            if p.description:
                lines.append(f"  - {p.description}")
        lines.append("")

    if avatars := getattr(brand, "avatars", None):
        lines.append("## Avatars")
        for a in avatars:
            tag = "PRIMARY" if a.is_primary else "secondary"
            lines.append(f"- **{a.name}** ({tag})")
            for key in sorted(a.data or {}):
                lines.append(f"  - {key}: {_clean(a.data[key])}")
        lines.append("")

    if competitors := getattr(brand, "competitors", None):
        lines.append("## Competitors")
        for c in competitors:
            lines.append(f"- **{c.name}** ({c.kind})")
            for key in sorted(c.data or {}):
                lines.append(f"  - {key}: {_clean(c.data[key])}")
        lines.append("")

    if voc := getattr(brand, "voc_entries", None):
        lines.append("## Voice of Customer — REAL customer language, verbatim")
        lines.append("Use these words in the copy. Prefer them over anything you would invent.")
        for entry in voc:
            lines.append(f'- [{entry.category}/{entry.source}] "{entry.text}"')
        lines.append("")

    core = brand.core or {}
    if core:
        lines.append("## Established strategy (output of earlier modules — stay consistent with it)")
        for key in sorted(core):
            value = _clean(core[key])
            if not value:
                continue
            lines.append(f"\n### {key}\n{value}")
        lines.append("")

    for key in sorted(extras or {}):
        if value := _clean((extras or {})[key]):
            lines.append(f"## {key}\n{value}\n")

    return "\n".join(lines).strip()


def build_task(module: Module, inputs: dict[str, Any], section: str | None = None) -> str:
    """The volatile half of the prompt: what to produce, right now."""
    parts: list[str] = ["# REQUEST", ""]

    if module.command:
        parts.append(f"Execute the skill's `{module.command}` command.")
    parts.append(f"Deliverable: **{module.title}** — {module.subtitle}")
    parts.append("")

    if module.instructions:
        parts += ["## Specific instructions", module.instructions, ""]

    if section:
        parts += [
            "## Section to produce now",
            f"Produce **{section}** only, in full depth.",
            "Do not write any other module, and do not summarise the ones already written.",
            "Assume the reader has the earlier sections in front of them.",
            "",
        ]

    supplied = {k: _clean(v) for k, v in inputs.items() if _clean(v) and k not in ("image", "video")}
    if supplied:
        parts.append("## Answers supplied for this run")
        for key in sorted(supplied):
            parts.append(f"- **{key}**: {supplied[key]}")
        parts.append("")

    if dialect := inputs.get("dialect"):
        parts.append(
            f"## Language\nAll consumer-facing copy in **{DIALECT_MAP.get(dialect, dialect)}**. "
            "Analysis in Arabic, with English technical terms preserved.\n"
        )

    parts.append("Begin the deliverable now.")
    return "\n".join(parts)
