import pytest

from binance_bot.exceptions import ConfigError
from binance_bot.market import SymbolRules
from binance_bot.strategy import SopParams, data_peak_signs, size_position
from binance_bot.strategy.sizing import Sizing
from fakes import peak_candles, rising_candles


@pytest.mark.parametrize(
    ("stop", "expected"),
    [(3, 0.50), (4, 0.56), (5, 0.61), (6, 0.65), (8, 0.71), (10, 0.75), (12, 0.78), (15, 0.82)],
)
def test_breakeven_matches_the_sop_chart(stop: float, expected: float) -> None:
    # PDF: target 4%, biaya 0,5% per trade; pada stop-loss 5% syaratnya sekitar 61%.
    assert SopParams(capital_usdt=1, stop_pct=stop).breakeven_win_rate == pytest.approx(
        expected, abs=0.006
    )


def test_params_require_capital_or_quantity_and_sane_values() -> None:
    with pytest.raises(ConfigError, match="MODAL"):
        SopParams().validate()
    with pytest.raises(ConfigError, match="RISIKO"):
        SopParams(capital_usdt=100, risk_pct=50).validate()
    with pytest.raises(ConfigError, match="SINYAL"):
        SopParams(capital_usdt=100, signal_source="feeling").validate()
    SopParams(quantity=10).validate()


RULES = SymbolRules(step=0.1, min_qty=0.1, min_notional=5.0)


def test_position_size_follows_the_sop_example() -> None:
    # PDF: modal 10.000.000, risiko 1%, stop-loss 5% -> ukuran posisi 2.000.000.
    sizing = size_position(SopParams(capital_usdt=10_000_000), 1.0, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.notional == pytest.approx(2_000_000)
    assert sizing.loss_at_stop == pytest.approx(100_000)


def test_quantity_is_floored_to_step_and_typed_with_comma() -> None:
    sizing = size_position(SopParams(capital_usdt=1000), 1.0833, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.quantity == pytest.approx(184.6)  # 200 / 1,0833 = 184,62 -> 184,6
    assert sizing.quantity_text == "184,6"


def test_manual_quantity_overrides_formula() -> None:
    sizing = size_position(SopParams(quantity=50.27), 1.0, RULES, decimal_separator=".")
    assert isinstance(sizing, Sizing)
    assert sizing.quantity_text == "50.2"


def test_sizing_refuses_orders_below_minimum_or_above_capital() -> None:
    assert "minimum" in str(size_position(SopParams(capital_usdt=10), 1.0, RULES))
    too_big = size_position(SopParams(capital_usdt=100, quantity=500), 1.0, RULES)
    assert "melebihi modal" in str(too_big)


def test_data_signs_on_a_textbook_peak() -> None:
    signs = data_peak_signs(peak_candles())
    assert signs.as_dict() == {
        "upper_wick": False,
        "failed_new_high": True,
        "volume_declining": True,
        "big_red_after_greens": True,
    }
    assert signs.count == 3


def test_data_signs_on_a_clean_uptrend() -> None:
    assert data_peak_signs(rising_candles()).count == 0


def test_data_signs_need_enough_closed_candles() -> None:
    with pytest.raises(ValueError):
        data_peak_signs(rising_candles(5))
