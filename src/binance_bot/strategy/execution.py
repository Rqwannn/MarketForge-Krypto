"""Langkah terakhir SOP: menekan Jual/Short. DIMATIKAN pada tahap pengembangan.

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
    notional: float
    entry_price: float
    target_price: float
    stop_price: float
    side: str = "SHORT"
    leverage: int = 1
    margin_mode: str = "ISOLATED"


class DryRunOrderGate:
    def submit(self, plan: OrderPlan) -> None:
        logger.warning(
            "[DRY RUN] Tombol Jual/Short TIDAK ditekan. Rencana: %s %s %s (~%.2f USDT) | "
            "masuk ~%g | target %g | stop-loss %g | %s %dx",
            plan.side,
            plan.quantity_text,
            plan.symbol,
            plan.notional,
            plan.entry_price,
            plan.target_price,
            plan.stop_price,
            plan.margin_mode,
            plan.leverage,
        )
