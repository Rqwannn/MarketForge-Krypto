"""Objek tiruan bersama untuk tes: tidak menyentuh aplikasi, layar, jaringan, atau AI sungguhan."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from binance_bot.analysis import AnalysisRecord, PatternReading
from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.config import DEFAULT_APP_ID
from binance_bot.exceptions import BotError, ScreenReadError
from binance_bot.macos import Rect, TextLine
from binance_bot.market import Candle, Quote, SymbolRules
from binance_bot.strategy import MaPattern, OrderPlan, candles_needed

BUNDLE = DEFAULT_APP_ID
WINDOW = Rect(x=0, y=33, width=1470, height=859)
# Area layar MacBook Air 13" M4 tanpa menu bar dan Dock (tempat ukuran kalibrasi diukur).
AREA = Rect(x=0, y=33, width=1470, height=862)
OK = MaPattern(below_count=3, below_now=True, below_recent=True)  # berkali-kali di bawah: boleh
WAIT = MaPattern(below_count=1, below_now=False, below_recent=False)  # baru sekali: tunggu
NEVER = MaPattern(below_count=0, below_now=False, below_recent=False)  # selalu di atas: jangan


def reading(pattern: MaPattern = OK) -> PatternReading:
    return PatternReading(pattern, "Garis kuning sudah beberapa kali di bawah magenta.")


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
        *,
        resizable: bool = True,
    ) -> None:
        self.rect = rect
        self.resizable = resizable
        self.events: list[tuple[str, object]] = []
        self._last: Rect | None = None
        self._texts = {rect.sub(*area): list(answers) for area, answers in (texts or {}).items()}

    def bounds(self, app_name: str) -> Rect:
        return self.rect

    def set_bounds(self, app_name: str, rect: Rect) -> None:
        self.events.append(("set_bounds", rect))
        if self.resizable:
            self.rect = rect

    def click(self, x: int, y: int) -> None:
        self.events.append(("click", (x, y)))

    def scroll_up(self, x: int, y: int) -> None:
        self.events.append(("scroll_up", (x, y)))

    def scroll_down(self, x: int, y: int, notches: int) -> None:
        self.events.append(("scroll_down", (x, y, notches)))

    def clear_field(self) -> None:
        self.events.append(("clear", None))

    def select_field(self) -> None:
        self.events.append(("select", None))

    def scroll_horizontal(self, x: int, y: int, notches: int) -> None:
        self.events.append(("scroll_horizontal", (x, y, notches)))

    def type_number(self, text: str) -> None:
        self.events.append(("type", text))

    def type_symbol(self, text: str) -> None:
        self.events.append(("type_symbol", text))

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


def ma_candles(drops: int) -> list[Candle]:
    """Candle 15 menit dengan `drops` kali MA7 turun di bawah MA25 (0..3) dalam 24 jam terakhir.

    Pada 3 kali, harga sedang turun sehingga MA7 juga di bawah MA25 di ujung kanan.
    """
    need = candles_needed()
    shapes = {
        0: [(need, 1.0)],
        1: [(70, 1.0), (8, -6.0), (need - 78, 1.5)],
        2: [(20, 1.0), (8, -6.0), (30, 1.5), (8, -6.0), (need - 66, 1.5)],  # lalu naik terus
        3: [(30, 1.0), (8, -6.0), (25, 1.5), (8, -6.0), (25, 1.5), (need - 96, -3.0)],
    }
    closes, price = [], 100.0
    for count, step in shapes[drops]:
        for _ in range(count):
            price += step
            closes.append(price)
    return [
        Candle(i * 900_000, c, c + 0.1, c - 0.1, c, 1.0, i * 900_000 + 899_999)
        for i, c in enumerate(closes)
    ]


class FakeMarket:
    def __init__(
        self,
        quote: Quote | None = None,
        candles: list[Candle] | None = None,
        rules: SymbolRules | None = None,
    ) -> None:
        self.q = quote or Quote(bid=1.0, ask=1.0005, change_pct=50.0)
        self.quotes: dict[str, Quote] = {}
        self.candles = candles if candles is not None else ma_candles(2)
        self.r = rules or SymbolRules(step=0.1, min_qty=0.1, min_notional=5.0)
        self.minute_candles: list[Candle] = []
        self.funding: list[tuple[int, float]] = []

    def quote(self, symbol: str) -> Quote:
        return self.quotes.get(symbol, self.q)

    def rules(self, symbol: str) -> SymbolRules:
        return self.r

    def klines(self, symbol: str, interval: str, **_: object) -> list[Candle]:
        return self.minute_candles if interval == "1m" else self.candles

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return self.funding


# --------------------------------------------------------------------------- workflow

SOP_MARGIN = MarginSettings(isolated=True, leverage=2)


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
        self.available: float | None = 1000.0  # saldo tersedia di form order
        self.calls: list[str] = []
        self.turns: list[tuple[int, int]] = []  # rentang `calls` di dalam giliran layar
        self.filled: list[str] = []

    @contextmanager
    def screen_turn(self) -> Iterator[None]:
        """Giliran layar: rentang indeks `calls` yang terjadi di dalam giliran dicatat."""
        start = len(self.calls)
        try:
            yield
        finally:
            self.turns.append((start, len(self.calls)))

    def outside_turns(self) -> list[str]:
        """Aksi layar di luar giliran (show_app hanya memunculkan aplikasi, bukan klik)."""
        inside = {i for start, end in self.turns for i in range(start, end)}
        return [
            c for i, c in enumerate(self.calls) if i not in inside and not c.startswith("show_app")
        ]

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

    def open_symbol(self, symbol: str) -> str:
        self.calls.append(f"open_symbol:{symbol}")
        rank = next((row.rank for row in self.rows if row.symbol == symbol), None)
        if rank is None:
            raise ScreenReadError(f"{symbol} sudah tidak di daftar top gainers")
        symbol_opened = self.symbols[rank]
        if isinstance(symbol_opened, BotError):
            raise symbol_opened
        return symbol_opened

    def search_symbol(self, symbol: str) -> str:
        self.calls.append(f"search_symbol:{symbol}")
        return symbol

    def show_app(self, text: str, **fields: object) -> None:
        self.calls.append(f"show_app:{fields.get('symbol') or fields.get('rank')}")

    def order_button(self, side: str) -> tuple[float, float]:
        self.calls.append("short_button" if side == "SHORT" else "long_button")
        return (0.9, 0.5)

    def press_order(self, plan: object) -> None:
        raise AssertionError("press_order tidak boleh dipanggil selama order dikunci")

    def close_position(self, symbol: str) -> None:
        self.calls.append(f"close_position:{symbol}")

    def available_usdt(self) -> float | None:
        return self.available

    def show_15m_chart(self) -> None:
        self.calls.append("15m")

    def capture_window(self, path: Path) -> Path:
        return self._capture(path)

    def capture_chart(self, path: Path) -> Path:
        return self._capture(path)

    def read_margin_settings(self) -> MarginSettings:
        return self.margin

    def ensure_leverage(self, leverage: int) -> MarginSettings:
        if self.margin.leverage != leverage:
            self.calls.append(f"leverage:{leverage}")
            self.margin = MarginSettings(self.margin.isolated, leverage)
        return self.margin

    def fill_quantity(self, text: str) -> None:
        self.calls.append(f"fill:{text}")
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


class FakePatternAnalyzer:
    """AI tiruan. `patterns` memetakan pair -> pola; selain itu `default`."""

    def __init__(self, default: MaPattern = OK, patterns: dict[str, MaPattern] | None = None):
        self.default = default
        self.patterns = patterns or {}
        self.calls: list[Path] = []

    def analyze(self, image: Path) -> PatternReading:
        self.calls.append(image)
        # Nama file: <waktu>_<PAIR>_rank<N>_15m.png. Cocokkan pair utuh (SUSDT != GRASSUSDT).
        symbol = next((s for s in self.patterns if f"_{s}_" in image.name), None)
        return reading(self.patterns[symbol] if symbol else self.default)


class Clock:
    """Jam tiruan: `sleep` memajukan waktu, jadi tes penantian berjalan instan."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
