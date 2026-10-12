import pytest

from binance_bot.exceptions import ConfigError
from binance_bot.market import SymbolRules
from binance_bot.strategy import MaPattern, SopParams, data_ma_pattern, size_position
from binance_bot.strategy.sizing import Sizing
from fakes import ma_candles


@pytest.mark.parametrize(
    ("stop", "expected"),
    [(1.5, 0.46), (2, 0.53), (3, 0.62), (5, 0.73), (8, 0.81), (10, 0.84), (15, 0.89), (25, 0.93)],
)
def test_breakeven_matches_the_v2_chart(stop: float, expected: float) -> None:
    # PDF V2: target 2%, biaya 0,1% per trade; pada stop-loss 2% syaratnya sekitar 53%.
    params = SopParams(capital_usdt=1, stop_pct=stop)
    assert params.breakeven_win_rate == pytest.approx(expected, abs=0.006)


def test_v2_defaults_follow_the_pdf() -> None:
    p = SopParams()
    assert (p.leverage, p.margin_pct, p.max_open_positions) == (2, 50.0, 2)
    assert (p.target_pct, p.stop_pct, p.fee_pct, p.min_crosses) == (2.0, 2.0, 0.1, 2)
    assert (p.max_hold_h, p.review_after_h, p.min_gain_pct) == (4.0, 1.0, 0.0)


def test_params_require_capital_or_quantity_and_sane_values() -> None:
    with pytest.raises(ConfigError, match="MODAL"):
        SopParams().validate()
    with pytest.raises(ConfigError, match="MARGIN"):
        SopParams(capital_usdt=100, margin_pct=150).validate()
    with pytest.raises(ConfigError, match="LEVERAGE"):
        SopParams(capital_usdt=100, leverage=50).validate()
    with pytest.raises(ConfigError, match="SINYAL"):
        SopParams(capital_usdt=100, signal_source="feeling").validate()
    SopParams(quantity=10).validate()


RULES = SymbolRules(step=0.1, min_qty=0.1, min_notional=5.0)


def test_position_size_follows_the_v2_example() -> None:
    # PDF: modal 10.000.000, margin 50% x 2x -> nilai posisi 10.000.000; SL 2% -> rugi 200.000.
    sizing = size_position(SopParams(capital_usdt=10_000_000), 1.0, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.notional == pytest.approx(10_000_000)
    assert sizing.margin_usdt == pytest.approx(5_000_000)
    assert sizing.loss_at_stop == pytest.approx(200_000)


def test_quantity_is_floored_to_step_and_typed_with_comma() -> None:
    sizing = size_position(SopParams(capital_usdt=100), 0.10999, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.quantity_text == "909,1"  # 100 x 50% x 2 / 0,10999 = 909,17 -> 909,1


def test_manual_quantity_overrides_formula_but_not_the_margin_limit() -> None:
    sizing = size_position(SopParams(quantity=50.27), 1.0, RULES, decimal_separator=".")
    assert isinstance(sizing, Sizing) and sizing.quantity_text == "50.2"
    too_big = size_position(SopParams(capital_usdt=100, quantity=500), 1.0, RULES)
    assert "melebihi 50% modal" in str(too_big)


def test_sizing_refuses_orders_below_exchange_minimum() -> None:
    assert "minimum" in str(size_position(SopParams(capital_usdt=2), 1.0, RULES))


@pytest.mark.parametrize(("count", "verdict"), [(0, "jangan"), (1, "tunggu"), (2, "ok"), (5, "ok")])
def test_yellow_line_rule(count: int, verdict: str) -> None:
    assert MaPattern(count, below_now=False).verdict(min_crosses=2) == verdict


def test_threshold_is_adjustable() -> None:
    assert MaPattern(2, False).verdict(min_crosses=3) == "tunggu"


@pytest.mark.parametrize(
    ("drops", "expected"),
    [
        (0, MaPattern(0, False)),
        (1, MaPattern(1, False)),
        (2, MaPattern(2, False)),
        (3, MaPattern(3, True)),
    ],
)
def test_data_counts_ma7_periods_below_ma25(drops: int, expected: MaPattern) -> None:
    assert data_ma_pattern(ma_candles(drops)) == expected


def test_data_pattern_needs_enough_candles() -> None:
    with pytest.raises(ValueError):
        data_ma_pattern(ma_candles(2)[:50])
