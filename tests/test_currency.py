"""Unit tests for currency conversion + display (docs/05-testing.md: Unit - currency)."""

from __future__ import annotations

from stackrank.currency import format_money, from_usd, to_usd


def test_from_usd_round_trips_to_original_sgd():
    usd_per_sgd = 0.78
    for base in (0.0, 12345.6789, -42.0):
        converted = from_usd(to_usd(base, usd_per_sgd), usd_per_sgd)
        assert abs(converted - base) < 1e-6


def test_format_money_includes_all_three_codes():
    text = format_money(1000, 0.78, 3.55)

    assert "S$" in text
    assert "US$" in text
    assert "RM" in text
