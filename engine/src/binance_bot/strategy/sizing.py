"""Ukuran posisi SOP V2: margin % modal x leverage.

Kolom "Jumlah" di Binance diisi dalam satuan USDT, mode "Ukuran Order" (nilai posisi), bukan
jumlah koin. Jumlah koin tetap dihitung (dibulatkan ke aturan koin) untuk jurnal dan pengecekan
minimum order, seperti yang akan dihasilkan Binance dari ukuran order itu.

Contoh PDF: modal 10.000.000, margin 50% = 5.000.000, leverage 2x -> nilai posisi 10.000.000
per koin. Rugi bila stop-loss kena = jarak stop-loss x nilai posisi.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from binance_bot.market import SymbolRules
from binance_bot.strategy.params import SopParams


@dataclass(frozen=True, slots=True)
class Sizing:
    quantity: float  # jumlah koin (perkiraan hasil Binance dari ukuran order)
    quantity_text: str  # jumlah koin untuk log, mis. "184,6"
    order_text: str  # yang diketik di kolom "Jumlah" (USDT, Ukuran Order), mis. "100" atau "99,50"
    notional: float  # nilai posisi (USDT)
    margin_usdt: float  # margin yang terpakai = nilai posisi / leverage
    loss_at_stop: float  # rugi bila stop-loss kena, sebelum biaya (USDT)


def floor_to_step(value: float, step: float) -> Decimal:
    step_d = Decimal(str(step))
    return (Decimal(str(value)) / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d


def format_quantity(quantity: Decimal, step: float, decimal_separator: str) -> str:
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return f"{quantity:.{decimals}f}".replace(".", decimal_separator)


USDT_STEP = 0.01


def format_usdt(value: Decimal, decimal_separator: str) -> str:
    """100.00 -> "100", 99.50 -> "99,50" (koma desimal untuk Binance bahasa Indonesia)."""
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value:.2f}".replace(".", decimal_separator)


def size_position(
    params: SopParams, price: float, rules: SymbolRules, decimal_separator: str = ","
) -> Sizing | str:
    """Hitung ukuran order (USDT) dan jumlah koin. Mengembalikan alasan (str) bila tidak bisa."""
    if price <= 0:
        return "harga tidak valid"
    if params.order_usdt is not None:
        order_usdt = params.order_usdt
    else:
        assert params.capital_usdt is not None
        order_usdt = params.capital_usdt * params.margin_pct / 100 * params.leverage
    order = floor_to_step(order_usdt, USDT_STEP)
    wanted = float(order) / price

    quantity = floor_to_step(wanted, rules.step)
    notional = float(quantity) * price
    margin = notional / params.leverage
    if quantity <= 0 or float(quantity) < rules.min_qty:
        return f"jumlah {wanted:.6g} di bawah minimum {rules.min_qty:g} koin"
    if notional < rules.min_notional:
        return f"nilai order {notional:.2f} USDT di bawah minimum {rules.min_notional:g} USDT"
    if params.capital_usdt is not None:
        allowed = params.capital_usdt * params.margin_pct / 100
        if margin > allowed * 1.0001:
            return f"margin {margin:.2f} USDT melebihi {params.margin_pct:g}% modal ({allowed:.2f})"
    return Sizing(
        quantity=float(quantity),
        quantity_text=format_quantity(quantity, rules.step, decimal_separator),
        order_text=format_usdt(order, decimal_separator),
        notional=notional,
        margin_usdt=margin,
        loss_at_stop=notional * params.stop_pct / 100,
    )
