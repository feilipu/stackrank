"""SGD-based currency conversion and blend scoring."""

from __future__ import annotations

BLEND_OUTCOME_WEIGHT = 0.6
BLEND_ELO_WEIGHT = 0.4
ELO_SCALE = 15.0

CURRENCIES = ("SGD", "USD", "MYR")
SYMBOLS = {"SGD": "S$", "USD": "US$", "MYR": "RM"}


def to_usd(sgd: float, usd_per_sgd: float) -> float:
    return sgd * usd_per_sgd


def to_myr(sgd: float, myr_per_sgd: float) -> float:
    return sgd * myr_per_sgd


def from_usd(usd: float, usd_per_sgd: float) -> float:
    if usd_per_sgd <= 0:
        raise ValueError("usd_per_sgd must be > 0")
    return usd / usd_per_sgd


def from_myr(myr: float, myr_per_sgd: float) -> float:
    if myr_per_sgd <= 0:
        raise ValueError("myr_per_sgd must be > 0")
    return myr / myr_per_sgd


def to_sgd(amount: float, currency: str, usd_per_sgd: float, myr_per_sgd: float) -> float:
    currency = (currency or "SGD").upper()
    if currency == "SGD":
        return amount
    if currency == "USD":
        return from_usd(amount, usd_per_sgd)
    if currency == "MYR":
        return from_myr(amount, myr_per_sgd)
    raise ValueError(f"unknown currency: {currency}")


def blend(outcome: float, elo_rating: float) -> float:
    return BLEND_OUTCOME_WEIGHT * outcome + BLEND_ELO_WEIGHT * (elo_rating / ELO_SCALE)


def metric_value(metric: str, outcome: float, elo_rating: float) -> float:
    metric = (metric or "outcome").lower()
    if metric == "outcome":
        return outcome
    if metric == "elo":
        return elo_rating
    if metric == "blend":
        return blend(outcome, elo_rating)
    raise ValueError(f"unknown metric: {metric}")


def format_money(sgd: float, usd_per_sgd: float, myr_per_sgd: float) -> str:
    return (
        f"S${sgd:,.0f}  ·  US${to_usd(sgd, usd_per_sgd):,.0f}  ·  "
        f"RM{to_myr(sgd, myr_per_sgd):,.0f}"
    )


def format_triple(sgd: float, usd_per_sgd: float, myr_per_sgd: float) -> dict[str, str]:
    return {
        "sgd": f"S${sgd:,.0f}",
        "usd": f"US${to_usd(sgd, usd_per_sgd):,.0f}",
        "myr": f"RM{to_myr(sgd, myr_per_sgd):,.0f}",
        "text": format_money(sgd, usd_per_sgd, myr_per_sgd),
    }
