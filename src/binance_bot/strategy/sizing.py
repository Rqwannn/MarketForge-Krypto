"""Ukuran posisi sesuai SOP: modal x %risiko / jarak stop-loss, dibulatkan ke aturan koin."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from binance_bot.market import SymbolRules
from binance_bot.strategy.params import SopParams


@dataclass(frozen=True, slots=True)
class Sizing:
    quantity: float  # jumlah koin
    quantity_text: str  # seperti yang diketik di kolom "Jumlah", mis. "184,6"
    notional: float  # nilai posisi dalam USDT (= margin pada leverage 1x)
    loss_at_stop: float  # rugi bila stop-loss kena, sebelum biaya (USDT)


def floor_to_step(value: float, step: float) -> Decimal:
    step_d = Decimal(str(step))
    return (Decimal(str(value)) / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d


def format_quantity(quantity: Decimal, step: float, decimal_separator: str) -> str:
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return f"{quantity:.{decimals}f}".replace(".", decimal_separator)


def size_position(
    params: SopParams, price: float, rules: SymbolRules, decimal_separator: str = ","
) -> Sizing | str:
    """Hitung jumlah koin. Mengembalikan alasan (str) bila order tidak bisa dibuat."""
    if price <= 0:
        return "harga tidak valid"
    if params.quantity is not None:
        wanted = params.quantity
    else:
        assert params.capital_usdt is not None
        risk_usdt = params.capital_usdt * params.risk_pct / 100
        # Leverage 1x: nilai posisi tidak boleh melebihi modal.
        notional = min(risk_usdt / (params.stop_pct / 100), params.capital_usdt)
        wanted = notional / price

    quantity = floor_to_step(wanted, rules.step)
    notional = float(quantity) * price
    if quantity <= 0 or float(quantity) < rules.min_qty:
        return f"jumlah {wanted:.6g} di bawah minimum {rules.min_qty:g} koin"
    if notional < rules.min_notional:
        return f"nilai order {notional:.2f} USDT di bawah minimum {rules.min_notional:g} USDT"
    if params.capital_usdt is not None and notional > params.capital_usdt * 1.0001:
        return f"nilai order {notional:.2f} USDT melebihi modal {params.capital_usdt:g} (1x)"
    return Sizing(
        quantity=float(quantity),
        quantity_text=format_quantity(quantity, rules.step, decimal_separator),
        notional=notional,
        loss_at_stop=notional * params.stop_pct / 100,
    )
