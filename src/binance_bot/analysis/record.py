from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from binance_bot.analysis.peak import PeakReading, peak_from_dict
from binance_bot.exceptions import AnalysisError
from binance_bot.market import is_futures_symbol


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    """Hasil AI tanda pucuk untuk satu pair Futures, dibagikan leader lewat hub.

    Kunci berbagi antar laptop adalah `symbol` (mis. "STRKUSDT"), bukan rank, karena
    peringkat Top Gainers bisa bergeser dalam hitungan detik.
    """

    symbol: str
    rank: int
    analyzed_at: float  # epoch detik, waktu panggilan AI
    reading: PeakReading

    def age_s(self, now: float) -> float:
        return now - self.analyzed_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rank": self.rank,
            "analyzed_at": self.analyzed_at,
            "signs": self.reading.signs.as_dict(),
            "summary": self.reading.summary,
        }

    @classmethod
    def from_dict(cls, data: Any) -> AnalysisRecord:
        """Validasi data dari luar (hub). Data yang tidak sesuai skema ditolak."""
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("symbol"), str)
            or not is_futures_symbol(data["symbol"])
            or not isinstance(data.get("rank"), int)
            or isinstance(data.get("rank"), bool)
            or not isinstance(data.get("analyzed_at"), int | float)
            or not isinstance(data.get("signs"), dict)
        ):
            raise AnalysisError(f"Data hasil analisis tidak sesuai skema: {str(data)[:200]}")
        return cls(
            symbol=data["symbol"],
            rank=data["rank"],
            analyzed_at=float(data["analyzed_at"]),
            reading=peak_from_dict({**data["signs"], "summary": data.get("summary")}),
        )
