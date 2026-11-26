"""API-provider usage, estimated cost, and spend limits.

Every call to an API provider records input/output tokens. When the
provider reports them (OpenAI-style `usage`, Anthropic's message usage)
they're marked `reported`; otherwise they're estimated from text length
(~4 characters per token) and marked as estimates. Cost is only computed
when you've entered the provider's prices (per million tokens) — Zenith
has no price list of its own and never claims to know your bill.

A monthly limit blocks further calls to that provider once this month's
estimated cost reaches it; a limit with no prices set can't be enforced
and the UI says so.
"""
from __future__ import annotations

import time
from datetime import datetime

from app.db.storage import _conn


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4) if text else 0


def _price(p: dict) -> tuple[float | None, float | None]:
    def num(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    return num(p.get("price_in")), num(p.get("price_out"))


def cost_of(p: dict, input_tokens: int, output_tokens: int) -> float | None:
    pin, pout = _price(p)
    if pin is None and pout is None:
        return None
    return (input_tokens * (pin or 0) + output_tokens * (pout or 0)) / 1_000_000


def record(p: dict, model: str, input_tokens: int, output_tokens: int, reported: bool) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO provider_usage (provider, model, input_tokens, output_tokens, reported, cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["id"], model, int(input_tokens), int(output_tokens), 1 if reported else 0,
             cost_of(p, input_tokens, output_tokens), time.time()),
        )


def _month_start() -> float:
    n = datetime.now()
    return datetime(n.year, n.month, 1).timestamp()


def month_summary(p: dict) -> dict:
    since = _month_start()
    with _conn() as conn:
        r = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
            " COALESCE(SUM(reported),0) FROM provider_usage WHERE provider = ? AND created_at >= ?",
            (p["id"], since),
        ).fetchone()
    calls, tin, tout, reported = r
    cost = cost_of(p, tin, tout)
    limit = p.get("monthly_limit")
    return {"provider": p["id"], "calls": calls, "input_tokens": tin, "output_tokens": tout,
            "all_reported": calls > 0 and reported == calls, "estimated_cost": round(cost, 4) if cost is not None else None,
            "monthly_limit": float(limit) if limit not in (None, "") else None,
            "prices_set": any(x is not None for x in _price(p))}


def check_limit(p: dict) -> None:
    """Raise ProviderError if this month's estimated spend reached the limit."""
    from app.services.providers import ProviderBlocked

    limit = p.get("monthly_limit")
    if limit in (None, "") or not any(x is not None for x in _price(p)):
        return
    s = month_summary(p)
    if s["estimated_cost"] is not None and s["estimated_cost"] >= float(limit):
        raise ProviderBlocked(
            f"{p.get('name', p['id'])} reached its monthly limit (≈${s['estimated_cost']:.2f} of ${float(limit):.2f}). "
            "Raise the limit in Settings → Providers or pick another model."
        )
