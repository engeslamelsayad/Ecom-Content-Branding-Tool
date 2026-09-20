"""Deterministic unit economics.

Language models are unreliable at arithmetic, so every number the tool asserts
about money is computed here and only interpreted by the model. The skill's
own simplified CAC-ceiling formula is reported alongside the fuller
contribution-margin model, since the plan quotes it by name.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass
class EconomicsInput:
    aov: float                      # average order value, ex-VAT
    cogs: float                     # cost of goods per order
    shipping_cost: float = 0.0      # fulfilment borne by the brand
    payment_fee_pct: float = 0.0    # gateway / COD collection fee, % of AOV
    return_rate_pct: float = 0.0    # share of orders refunded or refused
    purchases_per_year: float = 1.0
    lifespan_years: float = 1.0
    target_ltv_cac: float = 3.0
    current_cac: float | None = None
    currency: str = "EGP"


@dataclass
class EconomicsResult:
    gross_margin_pct: float
    contribution_per_order: float
    contribution_margin_pct: float
    ltv: float
    cac_ceiling: float
    cac_ceiling_skill_formula: float
    breakeven_roas: float
    target_roas: float
    orders_to_payback: float
    max_cpa_first_order: float
    current_ltv_cac: float | None
    verdict: str
    currency: str

    def to_dict(self) -> dict:
        return {key: (None if isinstance(value, float) and not math.isfinite(value) else value)
                for key, value in asdict(self).items()}


def compute(data: EconomicsInput) -> EconomicsResult:
    if data.aov <= 0:
        raise ValueError("AOV must be greater than zero")

    gross_profit = data.aov - data.cogs
    gross_margin_pct = gross_profit / data.aov * 100

    # Every order carries fulfilment and fees; returns destroy the whole order's
    # contribution while the goods cost is only partly recovered.
    fees = data.aov * data.payment_fee_pct / 100
    return_rate = max(0.0, min(data.return_rate_pct, 100.0)) / 100
    contribution = (gross_profit - data.shipping_cost - fees) * (1 - return_rate) - (
        data.shipping_cost * return_rate
    )
    contribution_margin_pct = contribution / data.aov * 100

    ltv = contribution * data.purchases_per_year * data.lifespan_years
    ratio = data.target_ltv_cac if data.target_ltv_cac > 0 else 3.0

    cac_ceiling = ltv / ratio
    # The marketing-plan skill states: (AOV x Gross Margin %) / Target LTV:CAC.
    cac_ceiling_skill = (data.aov * gross_margin_pct / 100) / ratio

    breakeven_roas = data.aov / contribution if contribution > 0 else float("inf")
    target_roas = breakeven_roas * ratio if contribution > 0 else float("inf")

    orders_to_payback = (
        data.current_cac / contribution
        if data.current_cac and contribution > 0
        else (1.0 if contribution > 0 else float("inf"))
    )
    current_ltv_cac = ltv / data.current_cac if data.current_cac else None

    if contribution <= 0:
        verdict = "خسارة على كل طلب — الوحدة الاقتصادية مكسورة قبل أي إنفاق إعلاني."
    elif current_ltv_cac is None:
        verdict = f"سقف الـ CAC هو {cac_ceiling:,.0f} {data.currency}. أي تكلفة اكتساب فوقه بتاكل الربح."
    elif current_ltv_cac >= ratio:
        verdict = f"صحي — LTV:CAC = {current_ltv_cac:.1f}:1 فوق الهدف {ratio:.0f}:1. في مساحة للتوسع."
    elif current_ltv_cac >= 1:
        verdict = f"هش — LTV:CAC = {current_ltv_cac:.1f}:1 تحت الهدف. قلّل الـ CAC أو ارفع الـ AOV."
    else:
        verdict = f"حرج — LTV:CAC = {current_ltv_cac:.1f}:1. بتخسر على كل عميل جديد."

    return EconomicsResult(
        gross_margin_pct=round(gross_margin_pct, 2),
        contribution_per_order=round(contribution, 2),
        contribution_margin_pct=round(contribution_margin_pct, 2),
        ltv=round(ltv, 2),
        cac_ceiling=round(cac_ceiling, 2),
        cac_ceiling_skill_formula=round(cac_ceiling_skill, 2),
        breakeven_roas=round(breakeven_roas, 2),
        target_roas=round(target_roas, 2),
        orders_to_payback=round(orders_to_payback, 2),
        max_cpa_first_order=round(contribution, 2),
        current_ltv_cac=round(current_ltv_cac, 2) if current_ltv_cac else None,
        verdict=verdict,
        currency=data.currency,
    )


def bundle_pricing(unit_price: float, unit_cost: float, tiers=(1, 2, 3),
                   discounts=(0.0, 10.0, 18.0), currency: str = "EGP") -> list[dict]:
    """Three-tier bundle maths for the /aov module, computed not guessed."""
    rows = []
    for qty, discount in zip(tiers, discounts):
        gross = unit_price * qty
        price = gross * (1 - discount / 100)
        cost = unit_cost * qty
        profit = price - cost
        rows.append({
            "qty": qty,
            "list_price": round(gross, 2),
            "bundle_price": round(price, 2),
            "discount_pct": discount,
            "customer_saves": round(gross - price, 2),
            "profit": round(profit, 2),
            "margin_pct": round(profit / price * 100, 2) if price else 0.0,
            "currency": currency,
        })
    return rows
