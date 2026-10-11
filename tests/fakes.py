"""Objek tiruan bersama untuk tes: tidak menyentuh aplikasi, layar, jaringan, atau AI sungguhan."""

from __future__ import annotations

from pathlib import Path

from binance_bot.analysis import AnalysisRecord, PeakReading
from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.exceptions import BotError
from binance_bot.macos import Rect, TextLine
from binance_bot.market import Candle, Quote, SymbolRules
from binance_bot.strategy import OrderPlan, PeakSigns

BUNDLE = "com.binance.BinanceDesktop"
WINDOW = Rect(x=0, y=33, width=1470, height=859)
THREE_SIGNS = PeakSigns(
    upper_wick=True, failed_new_high=True, volume_declining=True, big_red_after_greens=False
)
ONE_SIGN = PeakSigns(
    upper_wick=True, failed_new_high=False, volume_declining=False, big_red_after_greens=False
)


def reading(signs: PeakSigns = THREE_SIGNS) -> PeakReading:
    return PeakReading(signs, "Lilin terakhir bersumbu atas panjang.")


def record(symbol: str = "STRKUSDT", rank: int = 1, analyzed_at: float = 1000.0) -> AnalysisRecord:
    return AnalysisRecord(symbol, rank, analyzed_at, reading())


# --------------------------------------------------------------------------- layar


def text_lines(*texts: str) -> list[TextLine]:
    return [TextLine(text, 0.5, 0.1 + i * 0.1) for i, text in enumerate(texts)]


def list_lines(*rows: tuple[int, str, str]) -> list[TextLine]:
    """Baris daftar Futures (rank, nama, persen) pada posisi y yang benar di FUTURES_LIST_AREA."""
    _, top, _, bottom = layout.FUTURES_LIST_AREA
    lines = []
    for rank, name, percent in rows:
        window_y = layout.FUTURES_FIRST_ROW_Y + (rank - 1) * layout.FUTURES_ROW_STEP
        y = (window_y - top) / (bottom - top)
        lines += [TextLine(f"{name} Perpetual", 0.2, y), TextLine(percent, 0.8, y + 0.01)]
    return lines


class FakeApps:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.launched: list[str] = []

    def is_running(self, bundle_id: str) -> bool:
        return self.running

    def launch(self, bundle_id: str) -> None:
        self.launched.append(bundle_id)

    def frontmost_bundle_id(self) -> str | None:
        return BUNDLE


class FakeScreen:
    """Jendela + OCR tiruan. OCR menjawab sesuai area yang terakhir ditangkap.

    `texts` memetakan area layout (x0, y0, x1, y1) ke daftar jawaban berurutan; jawaban
    terakhir dipakai terus.
    """

    def __init__(
        self,
        rect: Rect = WINDOW,
        texts: dict[tuple[float, float, float, float], list[list[TextLine]]] | None = None,
    ) -> None:
        self.rect = rect
        self.events: list[tuple[str, object]] = []
        self._last: Rect | None = None
        self._texts = {rect.sub(*area): list(answers) for area, answers in (texts or {}).items()}

    def bounds(self, app_name: str) -> Rect:
        return self.rect

    def click(self, x: int, y: int) -> None:
        self.events.append(("click", (x, y)))

    def scroll_up(self, x: int, y: int) -> None:
        self.events.append(("scroll_up", (x, y)))

    def clear_field(self) -> None:
        self.events.append(("clear", None))

    def type_number(self, text: str) -> None:
        self.events.append(("type", text))

    def capture(self, rect: Rect, path: Path) -> None:
        self._last = rect

    def read_lines(self, image: Path) -> list[TextLine]:
        answers = self._texts.get(self._last) if self._last else None
        if not answers:
            return []
        return answers.pop(0) if len(answers) > 1 else answers[0]


# --------------------------------------------------------------------------- data pasar


def candle(o: float, h: float, low: float, c: float, v: float, i: int = 0) -> Candle:
    return Candle(i * 60_000, o, h, low, c, v, i * 60_000 + 59_999)


def rising_candles(n: int = 14) -> list[Candle]:
    """Naik terus dengan volume naik: tidak ada tanda pucuk."""
    return [candle(i, i + 1.1, i - 0.1, i + 1, 100 + 10 * i, i) for i in range(n)]


def peak_candles() -> list[Candle]:
    """3 dari 4 tanda: gagal high baru, volume menurun, lilin merah besar setelah hijau."""
    closed = [candle(i, i + 1.1, i - 0.1, i + 1, 100 + 10 * i, i) for i in range(7)]
    closed += [
        candle(7, 10, 6.9, 8, 300, 7),  # puncak
        candle(8, 9, 7.9, 8.5, 250, 8),
        candle(8.5, 9.2, 8.4, 8.8, 200, 9),
        candle(8.8, 9.3, 8.7, 8.9, 180, 10),
        candle(8.9, 9.4, 8.85, 9.0, 150, 11),
        candle(9.0, 9.6, 7.95, 8.0, 120, 12),  # merah besar
    ]
    return [*closed, candle(8, 8.1, 7.9, 8.05, 10, 13)]  # lilin yang masih berjalan


class FakeMarket:
    def __init__(
        self,
        quote: Quote | None = None,
        candles: list[Candle] | None = None,
        rules: SymbolRules | None = None,
    ) -> None:
        self.q = quote or Quote(bid=1.0, ask=1.0005, funding_rate=0.0001, change_pct=50.0)
        self.candles = candles if candles is not None else peak_candles()
        self.r = rules or SymbolRules(step=0.1, min_qty=0.1, min_notional=5.0)
        self.minute_candles: list[Candle] = []
        self.funding: list[tuple[int, float]] = []

    def quote(self, symbol: str) -> Quote:
        return self.q

    def rules(self, symbol: str) -> SymbolRules:
        return self.r

    def klines(self, symbol: str, interval: str, **_: object) -> list[Candle]:
        return self.minute_candles if interval == "1m" else self.candles

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return self.funding


# --------------------------------------------------------------------------- workflow

SOP_MARGIN = MarginSettings(isolated=True, leverage=1)


class FakeNavigator:
    """Navigator tiruan: `symbols` memetakan rank -> pair; nilai BotError = gagal dibuka."""

    def __init__(
        self,
        symbols: dict[int, str | BotError],
        rows: list[GainerRow] | None = None,
        margin: MarginSettings = SOP_MARGIN,
    ) -> None:
        self.symbols = symbols
        self.rows = (
            rows
            if rows is not None
            else [GainerRow(rank, s, 50.0) for rank, s in symbols.items() if isinstance(s, str)]
        )
        self.margin = margin
        self.calls: list[str] = []
        self.filled: list[str] = []

    def prepare(self) -> None:
        self.calls.append("prepare")

    def open_top_gainers(self) -> list[GainerRow]:
        self.calls.append("open_top_gainers")
        return self.rows

    def open_gainer(self, rank: int) -> str:
        self.calls.append(f"open_gainer:{rank}")
        symbol = self.symbols[rank]
        if isinstance(symbol, BotError):
            raise symbol
        return symbol

    def show_15m_chart(self) -> None:
        self.calls.append("15m")

    def capture_window(self, path: Path) -> Path:
        return self._capture(path)

    def capture_chart(self, path: Path) -> Path:
        return self._capture(path)

    def read_margin_settings(self) -> MarginSettings:
        return self.margin

    def fill_quantity(self, text: str) -> None:
        self.filled.append(text)

    def _capture(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return path


class FakeGate:
    def __init__(self) -> None:
        self.plans: list[OrderPlan] = []

    def submit(self, plan: OrderPlan) -> None:
        self.plans.append(plan)


class FakePeakAnalyzer:
    def __init__(self, signs: PeakSigns = THREE_SIGNS) -> None:
        self.signs = signs
        self.calls: list[Path] = []

    def analyze(self, image: Path) -> PeakReading:
        self.calls.append(image)
        return reading(self.signs)


class Clock:
    """Jam tiruan: `sleep` memajukan waktu, jadi tes penantian berjalan instan."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
