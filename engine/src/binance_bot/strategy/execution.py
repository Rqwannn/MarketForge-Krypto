"""Langkah 5 SOP: menekan Jual/Short atau Beli/Long, dan menutup posisi. Bawaan: uji kertas.

Pintu order bawaan adalah `DryRunOrderGate`: rencana dicatat dan posisi tombol order dicari
(tanpa klik). Order sungguhan (`ScreenOrderGate` -> `navigator.press_order`, dan
`navigator.close_position`) hanya jalan setelah `enable_live_orders()` dipanggil, yaitu saat
engine dijalankan dengan `--uang-sungguhan` (tombol Real Fund Trading, setelah modal peringatan
disetujui). Klik biasa navigator tetap menolak zona tombol order.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from binance_bot.exceptions import BotError, SafetyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    symbol: str
    order_text: str  # ukuran order USDT seperti diketik di kolom Jumlah
    quantity_text: str  # perkiraan jumlah koin
    notional: float  # nilai posisi (USDT)
    margin_usdt: float  # margin terpakai = nilai posisi / leverage
    entry_price: float
    target_price: float  # jual otomatis di target
    leverage: int
    side: str = "SHORT"  # SHORT | LONG (tombol yang ditekan)
    cutloss_price: float | None = None  # jual otomatis saat rugi (V4); None = tanpa cutloss
    margin_mode: str = "?"  # mode margin yang terbaca di bursa (bawaan bursa, Cross/Isolated)


# Kunci utama order sungguhan, per proses engine. Selama terkunci, tidak ada jalur kode yang
# menekan tombol order atau menutup posisi: pemanggilnya menolak sebelum mencari atau mengklik.
_live_orders = False


def enable_live_orders() -> None:
    """Buka kunci order sungguhan untuk proses ini (hanya dari CLI `--uang-sungguhan`)."""
    global _live_orders
    _live_orders = True
    logger.warning("MODE UANG SUNGGUHAN: tombol order dan tutup posisi di bursa akan ditekan")


def live_orders_enabled() -> bool:
    return _live_orders


class PositionCloser(Protocol):
    def close_position(self, symbol: str) -> None: ...


class OrderGate(Protocol):
    def submit(self, plan: OrderPlan) -> None: ...


class OrderPresser(Protocol):
    def press_order(self, plan: OrderPlan) -> None: ...


def button_name(side: str) -> str:
    return "Beli/Long" if side == "LONG" else "Jual/Short"


class ScreenOrderGate:
    """Pintu order sungguhan: menekan tombol order di aplikasi lewat navigator. DIKUNCI MATI."""

    def __init__(self, presser: OrderPresser) -> None:
        self._presser = presser

    def submit(self, plan: OrderPlan) -> None:
        if not live_orders_enabled():
            raise SafetyError("Order sungguhan terkunci (Real Fund Trading belum dinyalakan)")
        self._presser.press_order(plan)


class DryRunOrderGate:
    """Uji kertas: tombol tidak ditekan. Bila diberi `locate` (arah -> posisi), tombol order
    dicari (tanpa klik) supaya terbukti bot akan menemukannya saat order sungguhan diaktifkan."""

    def __init__(self, locate: Callable[[str], tuple[float, float]] | None = None) -> None:
        self._locate = locate

    def submit(self, plan: OrderPlan) -> None:
        button = button_name(plan.side)
        if self._locate is not None:
            try:
                x, y = self._locate(plan.side)
                logger.info("Tombol %s ditemukan di (%.3f, %.3f); TIDAK ditekan", button, x, y)
            except BotError as exc:
                logger.warning(
                    "Tombol %s tidak ditemukan (uji kertas tetap jalan): %s", button, exc
                )
        cutloss = (
            f"cutloss di {plan.cutloss_price:g}"
            if plan.cutloss_price is not None
            else "tanpa stop-loss"
        )
        logger.warning(
            "[DRY RUN] Tombol %s TIDAK ditekan. Rencana: %s %s USDT %s (~%s koin) | "
            "nilai ~%.2f USDT, "
            "margin ~%.2f USDT, %s %dx | masuk ~%g | jual otomatis di %g (%s)",
            button,
            plan.side,
            plan.order_text,
            plan.symbol,
            plan.quantity_text,
            plan.notional,
            plan.margin_usdt,
            plan.margin_mode,
            plan.leverage,
            plan.entry_price,
            plan.target_price,
            cutloss,
        )
