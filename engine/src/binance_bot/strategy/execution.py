"""Langkah 5 SOP: menekan Jual/Short, dan menutup posisi saat jual. Bawaan: uji kertas.

Pintu order bawaan adalah `DryRunOrderGate`: rencana dicatat dan posisi tombol Jual/Short dicari
(tanpa klik). Order sungguhan (`ScreenOrderGate` -> `navigator.press_short`, dan
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
    target_price: float  # jual otomatis (V3: tanpa stop-loss)
    leverage: int
    side: str = "SHORT"
    margin_mode: str = "?"  # mode margin yang terbaca di bursa (bawaan bursa, Cross/Isolated)


# Kunci utama order sungguhan, per proses engine. Selama terkunci, tidak ada jalur kode yang
# menekan Jual/Short atau menutup posisi: pemanggilnya menolak sebelum mencari atau mengklik.
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


class ShortPresser(Protocol):
    def press_short(self, plan: OrderPlan) -> None: ...


class ScreenOrderGate:
    """Pintu order sungguhan: menekan Jual/Short di aplikasi lewat navigator. DIKUNCI MATI."""

    def __init__(self, presser: ShortPresser) -> None:
        self._presser = presser

    def submit(self, plan: OrderPlan) -> None:
        if not live_orders_enabled():
            raise SafetyError("Order sungguhan terkunci (Real Fund Trading belum dinyalakan)")
        self._presser.press_short(plan)


class DryRunOrderGate:
    """Uji kertas: tombol tidak ditekan. Bila diberi `locate`, posisi tombol Jual/Short dicari
    (tanpa klik) supaya terbukti bot akan menemukannya saat order sungguhan diaktifkan."""

    def __init__(self, locate: Callable[[], tuple[float, float]] | None = None) -> None:
        self._locate = locate

    def submit(self, plan: OrderPlan) -> None:
        if self._locate is not None:
            try:
                x, y = self._locate()
                logger.info("Tombol Jual/Short ditemukan di (%.3f, %.3f); TIDAK ditekan", x, y)
            except BotError as exc:
                logger.warning(
                    "Tombol Jual/Short tidak ditemukan (uji kertas tetap jalan): %s", exc
                )
        logger.warning(
            "[DRY RUN] Tombol Jual/Short TIDAK ditekan. Rencana: %s %s USDT %s (~%s koin) | "
            "nilai ~%.2f USDT, "
            "margin ~%.2f USDT, %s %dx | masuk ~%g | jual otomatis di %g (tanpa stop-loss)",
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
        )
