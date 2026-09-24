"""Pricing endpoints.

These call the engine directly, so anything the API returns can be reproduced
from a script with the same package.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ifrs9qdb.engine import EclConfig, compute_ecl_one, compute_lgd, fallback_ead_curve

router = APIRouter(tags=["ecl"])


class LgdRequest(BaseModel):
    on_balance: float = Field(..., description="On-balance outstanding.")
    collateral_net: float = Field(0.0, description="Net collateral value.")
    base: float = 0.45
    unsecured_floor: float = 0.5


@router.post("/ecl/lgd")
def lgd(req: LgdRequest) -> dict:
    """Loss given default for one exposure.

    Included because the floor surprises people: collateral beyond about 50%
    coverage does not reduce the provision, and this makes that checkable.
    """
    value = compute_lgd(req.on_balance, req.collateral_net,
                        base=req.base, unsecured_floor=req.unsecured_floor)
    return {
        "lgd": value,
        "floor": req.base * req.unsecured_floor,
        "on_floor": abs(value - req.base * req.unsecured_floor) < 1e-12,
    }


class PriceRequest(BaseModel):
    contract_id: str = "adhoc"
    stage: int = 2
    on_balance: float
    collateral_net: float = 0.0
    cum_pd: list[float] = Field(..., description="Cumulative PD by month, zero-prepended.")
    eir: float = 0.05
    months_remaining: int = 12
    payment_type: int = 3
    payment_frequency: int = 1
    deferral: int = 0
    stage3_method: str = "full_outstanding"
    cap_ecl_at_exposure: bool = True


@router.post("/ecl/price")
def price(req: PriceRequest) -> dict:
    """Price a single contract, showing the curve it was priced against."""
    cfg = EclConfig(stage3_method=req.stage3_method,
                    cap_ecl_at_exposure=req.cap_ecl_at_exposure)
    result = compute_ecl_one(
        contract_id=req.contract_id, stage=req.stage, on_balance=req.on_balance,
        collateral_net=req.collateral_net, cum_pd=req.cum_pd, eir=req.eir,
        months_remaining=req.months_remaining, payment_type=req.payment_type,
        payment_frequency=req.payment_frequency, deferral=req.deferral, cfg=cfg,
    )
    curve = fallback_ead_curve(req.on_balance, req.months_remaining,
                               req.payment_type, req.payment_frequency, req.deferral)
    result["ead_curve"] = [round(float(x), 2) for x in curve[:24]]
    return result
