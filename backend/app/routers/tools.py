"""Deterministic tools: arithmetic the model is not allowed to guess at."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..calculators import EconomicsInput, bundle_pricing, compute
from ..deps import UserDep

router = APIRouter(prefix="/api/tools", tags=["tools"])


class EconomicsBody(BaseModel):
    aov: float = Field(gt=0)
    cogs: float = Field(ge=0)
    shipping_cost: float = Field(default=0, ge=0)
    payment_fee_pct: float = Field(default=0, ge=0, le=100)
    return_rate_pct: float = Field(default=0, ge=0, le=100)
    purchases_per_year: float = Field(default=1, gt=0)
    lifespan_years: float = Field(default=1, gt=0)
    target_ltv_cac: float = Field(default=3, gt=0)
    current_cac: float | None = Field(default=None, ge=0)
    currency: str = "EGP"


@router.post("/unit-economics")
async def unit_economics(body: EconomicsBody, user: UserDep):
    try:
        return compute(EconomicsInput(**body.model_dump())).to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class BundleBody(BaseModel):
    unit_price: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    discounts: list[float] = Field(default=[0, 10, 18])
    currency: str = "EGP"


@router.post("/bundles")
async def bundles(body: BundleBody, user: UserDep):
    tiers = tuple(range(1, len(body.discounts) + 1))
    return {"tiers": bundle_pricing(body.unit_price, body.unit_cost, tiers,
                                    tuple(body.discounts), body.currency)}
