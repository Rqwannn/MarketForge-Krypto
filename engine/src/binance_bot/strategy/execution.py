"""Langkah 5 SOP: menekan Jual/Short. DIKUNCI MATI pada tahap pengembangan.

Pintu order yang dipakai adalah `DryRunOrderGate`: rencana dicatat dan posisi tombol Jual/Short
dicari (tanpa klik). Logika order sungguhan sudah ada (`ScreenOrderGate` ->
`navigator.press_short`) tetapi menolak selama `LIVE_ORDERS_ENABLED` False. Klik biasa navigator
tetap menolak zona tombol order.
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
    target_price: float
    stop_price: float
    leverage: int
    side: str = "SHORT"
    margin_mode: str = "?"  # mode margin yang terbaca di bursa (bawaan bursa, Cross/Isolated)


# Kunci utama order sungguhan. Selama False, tidak ada jalur kode yang menekan Jual/Short:
# ScreenOrderGate dan navigator.press_short menolak sebelum mencari atau mengklik apa pun.
# Mengubahnya butuh keputusan sadar (fase uji 50 trade lulus, leverage 2x).
LIVE_ORDERS_ENABLED = False


class OrderGate(Protocol):
    def submit(self, plan: OrderPlan) -> None: ...


class ShortPresser(Protocol):
    def press_short(self, plan: OrderPlan) -> None: ...


class ScreenOrderGate:
    """Pintu order sungguhan: menekan Jual/Short di aplikasi lewat navigator. DIKUNCI MATI."""

    def __init__(self, presser: ShortPresser) -> None:
        self._presser = presser

    def submit(self, plan: OrderPlan) -> None:
        if not LIVE_ORDERS_ENABLED:
            raise SafetyError("Order sungguhan dinonaktifkan (LIVE_ORDERS_ENABLED = False)")
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
            "margin ~%.2f USDT, %s %dx | masuk ~%g | target %g | stop-loss %g",
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
            plan.stop_price,
        )
