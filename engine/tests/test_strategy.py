import pytest

from binance_bot.binance_desktop.pattern_rules import BINANCE
from binance_bot.exceptions import ConfigError
from binance_bot.market import SymbolRules
from binance_bot.strategy import (
    MaPattern,
    PatternProfile,
    SopParams,
    data_ma_pattern,
    size_position,
)
from binance_bot.strategy.sizing import Sizing
from binance_bot.tebbit_web.pattern_rules import TEBBIT
from fakes import ma_candles


@pytest.mark.parametrize(
    ("target", "loss", "expected"),
    [
        (3, 5, 0.64),
        (3, 10, 0.78),
        (3, 21.8, 0.88),
        (3, 25, 0.90),
        (3, 50, 0.95),
        (5, 5, 0.51),
        (5, 10, 0.67),
        (5, 21.8, 0.82),
        (5, 25, 0.84),
        (5, 50, 0.91),
    ],
)
def test_breakeven_matches_the_v3_chart(target: float, loss: float, expected: float) -> None:
    # Grafik Titik impas V3: target 3%/5%, biaya 0,1%, rugi = kenaikan harga yang ditanggung.
    params = SopParams(capital_usdt=1, target_pct=target)
    assert params.breakeven_win_rate(loss) == pytest.approx(expected, abs=0.006)


def test_without_real_losses_the_breakeven_uses_the_strk_example() -> None:
    assert SopParams(capital_usdt=1).breakeven_win_rate() == pytest.approx(0.88, abs=0.006)


def test_v3_defaults_follow_the_pdf() -> None:
    p = SopParams()
    assert (p.leverage, p.margin_pct) == (2, 50.0)
    assert (p.target_pct, p.fee_pct, p.min_crosses) == (3.0, 0.1, 2)  # tanpa stop-loss
    assert (p.review_after_h, p.min_gain_pct) == (24.0, 0.0)  # tanpa batas waktu


def test_params_require_capital_or_quantity_and_sane_values() -> None:
    with pytest.raises(ConfigError, match="MODAL"):
        SopParams().validate()
    with pytest.raises(ConfigError, match="MARGIN"):
        SopParams(capital_usdt=100, margin_pct=150).validate()
    with pytest.raises(ConfigError, match="LEVERAGE"):
        SopParams(capital_usdt=100, leverage=50).validate()
    with pytest.raises(ConfigError, match="SINYAL"):
        SopParams(capital_usdt=100, signal_source="feeling").validate()
    SopParams(order_usdt=10).validate()


RULES = SymbolRules(step=0.1, min_qty=0.1, min_notional=5.0)


def test_position_size_follows_the_v3_example() -> None:
    # PDF: modal 10.000.000, margin 50% x 2x -> nilai posisi 10.000.000, margin 5.000.000.
    sizing = size_position(SopParams(capital_usdt=10_000_000), 1.0, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.notional == pytest.approx(10_000_000)
    assert sizing.margin_usdt == pytest.approx(5_000_000)


def test_order_size_is_typed_in_usdt_and_coins_are_estimated() -> None:
    # Kolom Jumlah Binance: satuan USDT, mode Ukuran Order -> diketik nilai posisi, bukan koin.
    sizing = size_position(SopParams(capital_usdt=100), 0.10999, RULES)
    assert isinstance(sizing, Sizing)
    assert sizing.order_text == "100"  # 100 x 50% x 2 = 100 USDT
    assert sizing.quantity_text == "909,1"  # perkiraan koin: 100 / 0,10999 = 909,17 -> 909,1
    odd = size_position(SopParams(capital_usdt=99.555), 1.0, RULES)
    assert isinstance(odd, Sizing) and odd.order_text == "99,55"  # dibulatkan ke bawah, koma


def test_manual_order_size_overrides_formula_but_not_the_margin_limit() -> None:
    sizing = size_position(SopParams(order_usdt=50.27), 1.0, RULES, decimal_separator=".")
    assert isinstance(sizing, Sizing) and sizing.order_text == "50.27"
    assert sizing.quantity_text == "50.2"
    too_big = size_position(SopParams(capital_usdt=100, order_usdt=500), 1.0, RULES)
    assert "melebihi 50% modal" in str(too_big)


def test_sizing_refuses_orders_below_exchange_minimum() -> None:
    assert "minimum" in str(size_position(SopParams(capital_usdt=2), 1.0, RULES))


PROFILES = [BINANCE, TEBBIT]  # pemahaman yang sama untuk sementara, aturannya dipisah


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.platform)
@pytest.mark.parametrize(("count", "verdict"), [(0, "jangan"), (1, "tunggu"), (2, "ok"), (5, "ok")])
def test_yellow_line_rule(profile: PatternProfile, count: int, verdict: str) -> None:
    pattern = MaPattern(count, below_now=False, below_recent=True)
    assert profile.verdict(pattern, 2) == verdict


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.platform)
def test_threshold_is_adjustable(profile: PatternProfile) -> None:
    assert profile.verdict(MaPattern(2, False, True), 3) == "tunggu"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.platform)
def test_drops_before_the_rally_do_not_make_it_ok(profile: PatternProfile) -> None:
    # SOP V2: kenaikan harus mulai habis. Turun 3x sebelum lonjakan, lalu naik terus = TUNGGU.
    assert profile.verdict(MaPattern(3, below_now=False, below_recent=False), 2) == "tunggu"


@pytest.mark.parametrize(
    ("drops", "expected"),
    [
        (0, MaPattern(0, False, False)),
        (1, MaPattern(1, False, False)),
        (2, MaPattern(2, False, False)),  # dua kali turun, lalu naik terus 6 jam terakhir
        (3, MaPattern(3, True, True)),
    ],
)
def test_data_counts_ma7_periods_below_ma25(drops: int, expected: MaPattern) -> None:
    assert data_ma_pattern(ma_candles(drops)) == expected


def test_data_pattern_needs_enough_candles() -> None:
    with pytest.raises(ValueError):
        data_ma_pattern(ma_candles(2)[:50])
