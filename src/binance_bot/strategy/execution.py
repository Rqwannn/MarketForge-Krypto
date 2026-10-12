"""Langkah 5 SOP: menekan Jual/Short. DIMATIKAN pada tahap pengembangan.

Satu-satunya "pintu order" di engine adalah `DryRunOrderGate`, yang hanya mencatat rencana.
Tidak ada kode yang menekan tombol order, dan navigator menolak klik ke zona tombol order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    symbol: str
    quantity_text: str
    notional: float  # nilai posisi (USDT)
    margin_usdt: float  # margin terpakai = nilai posisi / leverage
    entry_price: float
    target_price: float
    stop_price: float
    leverage: int
    side: str = "SHORT"
    margin_mode: str = "ISOLATED"  # usulan SOP V2; bila tetap Cross, stop-loss wajib


class DryRunOrderGate:
    def submit(self, plan: OrderPlan) -> None:
        logger.warning(
            "[DRY RUN] Tombol Jual/Short TIDAK ditekan. Rencana: %s %s %s | nilai ~%.2f USDT, "
            "margin ~%.2f USDT, %s %dx | masuk ~%g | target %g | stop-loss %g",
            plan.side,
            plan.quantity_text,
            plan.symbol,
            plan.notional,
            plan.margin_usdt,
            plan.margin_mode,
            plan.leverage,
            plan.entry_price,
            plan.target_price,
            plan.stop_price,
        )
