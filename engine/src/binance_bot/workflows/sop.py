"""Inti SOP "Top Gainers (Short dan Long)" untuk satu koin yang halaman trade-nya terbuka.

Dipakai bersama oleh mode single (AI sendiri) dan follower (AI dari hub leader). Urutan:
cek slot (koin berikutnya hanya bila posisi terbuka tidak rugi; jumlah posisi tidak dibatasi),
saringan gratis (spread, kenaikan minimal bila diisi; funding rate tidak dipakai), pola garis
kuning MA7 (AI atau data) untuk short dan tanda LONG bila dipilih, ukuran posisi (margin 50% x
2x), leverage 2x di bursa, isi kolom Jumlah, lalu pintu order yang DIMATIKAN. Semua dicatat.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from binance_bot.analysis import PatternReading
from binance_bot.binance_desktop.pattern_rules import BINANCE
from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.config import Settings
from binance_bot.exceptions import (
    BotError,
    MarketDataError,
    NoHistoryError,
    PositionNotFoundError,
    ScreenReadError,
)
from binance_bot.filelock import exclusive
from binance_bot.logging_setup import event
from binance_bot.market import MarketData
from binance_bot.strategy import (
    Journal,
    JournalEntry,
    LongPattern,
    MaPattern,
    OrderGate,
    OrderPlan,
    PatternProfile,
    PositionCloser,
    SopParams,
    candles_needed,
    data_ma_pattern,
    evaluate_by_price,
    evaluate_open_trades,
    exit_price,
    live_orders_enabled,
    long_numbers,
    ma_gap_pct,
    size_position,
)
from binance_bot.strategy.evaluate import entry_price_of, gain_pct
from binance_bot.strategy.params import HOLD_GREEN_H, HOLD_MAX_H
from binance_bot.workflows.base import TradingNavigator

logger = logging.getLogger(__name__)

# Mengambil hasil AI untuk (pair, screenshot grafik 15 menit, baca juga tanda LONG?).
ReadingSource = Callable[[str, Path, bool], PatternReading]

_VERDICT_TEXT = {
    "jangan": "JANGAN (garis kuning selalu di atas)",
    "tunggu": "TUNGGU (baru sekali di bawah)",
    "ok": "OK (berkali-kali di bawah)",
}
_SIGN_TEXT = {1: "turun tajam lalu berbalik", 2: "posisi datar", 3: "garis cepat jauh di atas"}
_EXIT_TEXT = {
    "target": "jual (target tercapai)",
    "stop": "jual (cutloss)",
    "timeout": "jual (batas waktu)",
    "likuidasi": "jual (likuidasi)",
}


def short_reason(pattern: MaPattern, verdict: str, min_crosses: int) -> str:
    """Alasan tidak masuk short (aturan short tidak berubah sejak V3)."""
    if verdict == "tunggu" and pattern.lines_close and pattern.below_recent:
        return (
            "pola garis kuning TUNGGU (garis MA7 dan MA25 berdekatan; masuk hanya bila berjauhan)"
        )
    if verdict == "tunggu" and pattern.below_count >= min_crosses:
        return (
            f"pola garis kuning TUNGGU (sudah {pattern.below_count} kali di bawah, "
            "tapi 6 jam terakhir naik terus)"
        )
    return f"pola garis kuning {_VERDICT_TEXT[verdict]}"


def signs_text(signs: Sequence[int]) -> str:
    return ", ".join(f"tanda {n} ({_SIGN_TEXT[n]})" for n in signs)


@dataclass(frozen=True, slots=True)
class Decision:
    side: str | None  # "short" | "long" | None = tidak masuk
    verdict: str  # jangan | tunggu | ok (short) | long | konflik
    reason: str  # alasan tidak masuk (kosong bila masuk)


def decide(
    short: MaPattern,
    long: LongPattern | None,
    sides: Sequence[str],
    params: SopParams,
    profile: PatternProfile,
) -> Decision:
    """Arah masuk dari bacaan grafik dan arah yang boleh di Top ini (`params.sides_for`).

    Short memakai aturan profil apa adanya. LONG cukup satu tanda (usulan SOP 23 Okt). Grafik yang
    memenuhi syarat short sekaligus menunjukkan tanda LONG tidak dimasuki (usulan SOP: diputuskan
    manual). Tanpa arah LONG (`long` None), hasilnya sama persis dengan aturan short sebelumnya.
    """
    if not sides:
        return Decision(None, "tunggu", "Top ini tidak dipilih untuk short maupun long")
    short_verdict = profile.verdict(short, params.min_crosses)
    signs = long.signs if long is not None and "long" in sides else []
    if short_verdict == "ok" and signs:
        return Decision(
            None,
            "konflik",
            f"grafik memenuhi syarat SHORT dan menunjukkan {signs_text(signs)}; tidak masuk",
        )
    if short_verdict == "ok" and "short" in sides:
        return Decision("short", "ok", "")
    if signs:
        return Decision("long", "long", "")
    reasons = []
    if "short" in sides:
        reasons.append(short_reason(short, short_verdict, params.min_crosses))
    elif short_verdict == "ok":
        reasons.append("pola cocok untuk SHORT, tetapi arah SHORT tidak dipilih")
    if "long" in sides:
        reasons.append("tanda LONG tidak terbaca" if long is None else "tidak ada tanda LONG")
    verdict = short_verdict if "short" in sides or short_verdict == "ok" else "tunggu"
    return Decision(None, verdict, "; ".join(reasons))


def limits_of(params: SopParams) -> dict[str, float]:
    """Batas SOP untuk menilai koin; kartu alasan di aplikasi membandingkan angka dengannya."""
    return {
        "min_crosses": params.min_crosses,
        "max_spread_pct": params.max_spread_pct,
        "min_gain_pct": params.min_gain_pct,
    }


def decision_fields(entry: JournalEntry, params: SopParams | None = None) -> dict[str, Any]:
    """Angka di balik keputusan satu koin: bahan kartu "kenapa" di aplikasi."""
    fields: dict[str, Any] = {
        "change_pct": entry.change_pct,
        "spread_pct": entry.spread_pct,
        "ma_gap_pct": entry.ma_gap_pct,  # positif = garis cepat di bawah pembanding
        "ai": entry.pattern_ai,
        "data": entry.pattern_data,
        "side": entry.side,
        "long_ai": entry.long_ai,
        "long_data": entry.long_data,
        "long_signs": entry.long_signs,
        "leverage": entry.leverage,
        "margin_usdt": entry.margin_usdt,
        "notional": entry.notional,
    }
    if params is not None:
        fields["limits"] = limits_of(params)
    return fields


def coin_event(entry: JournalEntry, params: SopParams | None = None) -> dict[str, dict[str, Any]]:
    """Hasil penilaian satu koin untuk aplikasi desktop (lihat logging_setup.event)."""
    ai = entry.pattern_ai or {}
    data = entry.pattern_data or {}
    return event(
        "coin",
        **decision_fields(entry, params),
        rank=entry.rank,
        symbol=entry.symbol,
        status=entry.status,
        verdict=entry.verdict,
        count_ai=ai.get("below_count"),
        count_data=data.get("below_count"),
        summary=entry.ai_summary,
        reason=entry.reason,
        entry_price=entry.entry_price,
        target_price=entry.target_price,
        cutloss_price=entry.cutloss_price,
        real=entry.real,
        chart=chart_of(entry),
    )


def chart_of(entry: JournalEntry) -> str | None:
    """Screenshot grafik 15 menit yang dibaca AI (yang terakhir diambil), bila ada."""
    return next((s for s in reversed(entry.screenshots) if s.endswith("_15m.png")), None)


class _Skip(Exception):
    """Koin gugur di salah satu saringan SOP; pesan = alasannya."""


def log_top_gainers(rows: Sequence[GainerRow]) -> None:
    logger.info(
        "Top gainers Futures: %s",
        ", ".join(f"#{r.rank} {r.symbol} {r.change_pct:+.2f}%" for r in rows) or "-",
    )


# Jual otomatis (Aturan SELL V3) memeriksa posisi terbuka sesering ini selama bot menunggu
# putaran berikutnya. Binance memakai data publik (tanpa layar); Tebbit membaca harga dari layar
# (OCR, tanpa AI) sehingga lebih jarang.
WATCH_INTERVAL_S = {"binance": 60.0, "tebbit": 300.0}
# Bursa tanpa riwayat candle: posisi uji kertas hanya bisa dinilai dari harga saat dicek, jadi
# target, cutloss, dan batas waktunya tercatat tepat hanya bila bot terus mengawasinya.
PRICE_ONLY_PLATFORMS = ("tebbit",)


def refresh_journal(
    journal: Journal, market: MarketData, fee_pct: float, now_s: float
) -> list[JournalEntry]:
    """Langkah 6 SOP: nilai posisi uji yang masih terbuka dari candle sungguhan."""
    entries = journal.load()
    return record_changes(journal, entries, evaluate_open_trades(entries, market, now_s, fee_pct))


def refresh_by_price(
    journal: Journal,
    market: MarketData,
    fee_pct: float,
    now_s: float,
    closer: PositionCloser | None = None,
) -> list[JournalEntry]:
    """Jual otomatis dari harga terkini (Tebbit dari layar OCR; Binance uang sungguhan)."""
    if live_orders_enabled() and closer is not None:
        return _sell_due_positions(journal, market, fee_pct, now_s, closer)
    entries = journal.load()
    updated = []
    for entry in entries:
        if entry.status == "open" and entry.entry_price and entry.target_price and not entry.real:
            try:
                price = exit_price(entry, market.quote(entry.symbol))
            except BotError as exc:
                logger.warning("Harga %s belum terbaca untuk jual otomatis: %s", entry.symbol, exc)
            else:
                entry = evaluate_by_price(entry, price, now_s, fee_pct)
        updated.append(entry)
    return record_changes(journal, entries, updated)


def _sell_due_positions(
    journal: Journal,
    market: MarketData,
    fee_pct: float,
    now_s: float,
    closer: PositionCloser,
) -> list[JournalEntry]:
    """Jual otomatis uang sungguhan, satu posisi pada satu waktu dan satu bot pada satu waktu.

    Dua posisi bisa mencapai target bersamaan (atau dua bot menjalankan penjualan bersamaan),
    sedangkan penjualan memakai layar bursa. Karena itu semuanya bergiliran: kunci antar-proses
    menahan bot yang datang belakangan, lalu jurnal dibaca ulang (bot lain mungkin sudah menjual)
    dan harga setiap posisi dibaca ulang tepat sebelum diputuskan. Posisi berikutnya baru
    dijual bila harga SAAT ITU masih di target; kalau sudah memantul, posisinya tetap terbuka.
    Cutloss dan batas waktu (bila dinyalakan) memakai jalur yang sama.
    """
    with exclusive(journal.path.with_suffix(".sell.lock")):
        entries = journal.load()
        updated = []
        for entry in entries:
            if not (entry.status == "open" and entry.entry_price and entry.target_price):
                updated.append(entry)
                continue
            try:
                # Dibaca ulang sesudah menunggu giliran: ask untuk short, bid untuk long.
                price = exit_price(entry, market.quote(entry.symbol))
            except BotError as exc:
                logger.warning("Harga %s belum terbaca untuk jual otomatis: %s", entry.symbol, exc)
                updated.append(entry)
                continue
            result = evaluate_by_price(entry, price, now_s, fee_pct)
            if entry.real:
                logger.info(
                    "Cek ulang %s sebelum menjual: %s %g, target %g%s -> %s",
                    entry.symbol,
                    "bid" if entry.side == "long" else "ask",
                    price,
                    entry.target_price,
                    f", cutloss {entry.cutloss_price:g}" if entry.cutloss_price else "",
                    _EXIT_TEXT.get(result.status, "jual")
                    if result.is_closed
                    else "tahan (target belum tercapai)",
                )
                if result.is_closed:
                    try:
                        closer.close_position(entry.symbol)
                    except PositionNotFoundError:
                        # Jurnal mencatat terbuka, bursa tidak: biasanya ditutup manual. Aplikasi
                        # menanyakannya ke pengguna; bot tidak mengubah catatan sendiri.
                        logger.warning(
                            "Posisi %s tidak ada lagi di tab Posisi Binance: kemungkinan sudah "
                            "ditutup manual. Catat penutupannya di menu Posisi bila benar.",
                            entry.symbol,
                            extra=event("position_missing", symbol=entry.symbol),
                        )
                        result = entry
                    except BotError as exc:
                        logger.error(
                            "Jual otomatis %s GAGAL di bursa, posisi tetap terbuka: %s",
                            entry.symbol,
                            exc,
                        )
                        result = entry
            updated.append(result)
        return record_changes(journal, entries, updated)


def record_changes(
    journal: Journal, before: list[JournalEntry], after: list[JournalEntry]
) -> list[JournalEntry]:
    """Simpan hasil penilaian posisi dan catat posisi yang selesai (jual otomatis).

    Uang sungguhan: posisi sudah ditutup di bursa oleh pemanggil sebelum sampai ke sini.
    Uji kertas: hanya dicatat, tombol di bursa tidak ditekan.
    """
    live = live_orders_enabled()
    changed = [new for old, new in zip(before, after, strict=True) if old != new]
    for entry in changed:
        if entry.is_closed:
            logger.warning(
                (
                    "Posisi ditutup di bursa. "
                    if live and entry.real
                    else "[DRY RUN] Tombol tutup posisi TIDAK ditekan. "
                )
                + "Jual otomatis %s (%s) di %g: %+.2f%% posisi (%+.2f USDT = %+.2f%% modal)",
                entry.symbol,
                entry.status,
                entry.exit_price or 0,
                entry.pnl_pct or 0,
                entry.pnl_usdt or 0,
                entry.pnl_capital_pct or 0,
                extra=event(
                    "sell",
                    symbol=entry.symbol,
                    status=entry.status,
                    real=live and entry.real,
                    exit_price=entry.exit_price,
                    pnl_pct=entry.pnl_pct,
                    pnl_usdt=entry.pnl_usdt,
                ),
            )
    # Ditulis di atas isi jurnal terbaru: bot lain mungkin menambah catatan sejak `before` dibaca.
    return journal.replace(changed) if changed else after


class SopTrader:
    def __init__(
        self,
        settings: Settings,
        params: SopParams,
        navigator: TradingNavigator,
        market: MarketData,
        journal: Journal,
        gate: OrderGate,
        *,
        fill_form: bool = True,
        role: str = "single",
        profile: PatternProfile = BINANCE,
        wall_clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        params.validate()
        self.params = params
        self._settings = settings
        self._nav = navigator
        self._market = market
        self._journal = journal
        self._gate = gate
        self._fill_form = fill_form
        self._role = role
        self.profile = profile  # aturan pola platform ini
        self._wall_clock = wall_clock
        self._now = now

    @property
    def watch_interval_s(self) -> float:
        return WATCH_INTERVAL_S.get(self.profile.platform, 60.0)

    def _require_balance(self, margin_usdt: float) -> None:
        """Uang sungguhan: masuk hanya bila saldo tersedia di bursa cukup untuk margin posisi.

        Tanpa ini Binance menolak order, sedangkan bot tidak tahu dan mencatat posisi hantu.
        Saldo dibaca dari form order (baris "Tersedia"); tidak terbaca dianggap tidak cukup.
        """
        available = self._nav.available_usdt()
        needed = margin_usdt * 1.01  # sedikit ruang untuk biaya transaksi
        if available is None:
            raise _Skip("saldo tersedia tidak terbaca di form order; tidak masuk demi keamanan")
        if available < needed:
            raise _Skip(
                f"saldo tersedia {available:.2f} USDT kurang dari margin {margin_usdt:.2f} USDT"
            )

    def _capital_from_balance(self, entry: JournalEntry, share: float) -> SopParams:
        """Modal Max / Setengah: modal = `share` x saldo USDT tersedia di form order SAAT INI
        (rumus SOP tetap: tiap posisi memakai separuh modal, 2x).

        Dibaca ulang setiap koin, jadi posisi berikutnya memakai sisa saldo setelah margin posisi
        sebelumnya terpakai. Tidak terbaca atau kosong = tidak masuk.
        """
        label = "Modal Max" if share >= 1 else f"Modal {share * 100:g}% saldo"
        available = self._nav.available_usdt()
        if available is None:
            raise _Skip(f"{label}: saldo tersedia tidak terbaca di form order")
        if available <= 0:
            raise _Skip(f"{label}: saldo tersedia 0 USDT")
        capital = round(available * share, 2)
        logger.info("%s: saldo tersedia %.2f USDT, modal %.2f USDT", label, available, capital)
        entry.capital_usdt = capital
        return replace(self.params, capital_usdt=capital, capital_share=None)

    def positions_to_watch(self) -> int:
        """Posisi yang wajib diawasi bot sampai selesai: semua posisi uang sungguhan, dan posisi
        uji kertas di bursa tanpa candle. Uji kertas Binance dinilai ulang dari candle 1 menit
        kapan pun bot berjalan lagi, jadi tidak perlu ditunggui."""
        live = live_orders_enabled()
        price_only = self.profile.platform in PRICE_ONLY_PLATFORMS
        return sum(
            1
            for e in self._journal.load()
            if e.status == "open" and ((e.real and live) or (price_only and not e.real))
        )

    def real_positions_open(self) -> int:
        """Jumlah posisi uang sungguhan yang masih terbuka (yang wajib diawasi sampai terjual)."""
        if not live_orders_enabled():
            return 0
        return sum(1 for e in self._journal.load() if e.status == "open" and e.real)

    def refresh_journal(self) -> list[JournalEntry]:
        """Jual otomatis: posisi yang sudah mencapai target (atau cutloss/batas waktu bila
        dinyalakan) ditutup dan dicatat.

        Real Fund Trading memakai harga SAAT INI, bukan riwayat candle: posisi sungguhan hanya
        ditutup bila harga sekarang sudah di target (bukan bila tadi sempat menyentuhnya).
        """
        if live_orders_enabled():
            return self._refresh_by_price()
        try:
            return refresh_journal(
                self._journal, self._market, self.params.fee_pct, self._wall_clock()
            )
        except NoHistoryError:  # bursa tanpa candle (Tebbit): harga terkini dari layar
            return self._refresh_by_price()
        except MarketDataError as exc:
            logger.warning("Posisi uji belum bisa dinilai: %s", exc)
            return self._journal.load()

    def sell_due(self) -> list[str]:
        """Jual otomatis (lihat `refresh_journal`), lalu pair yang baru terjual di target.

        Terjual di target = harga sedang bergerak searah posisi (momentum): putaran berikutnya
        dimulai segera dan koin itu dicek ulang lebih dulu, tetap dengan semua aturan masuk. Jual
        karena cutloss atau batas waktu tidak dicek ulang.
        """
        before = {(e.id, e.created_at) for e in self._journal.load() if e.status == "open"}
        return [
            e.symbol
            for e in self.refresh_journal()
            if e.status == "target" and (e.id, e.created_at) in before
        ]

    def reentry_blocker(self, symbol: str) -> str | None:
        """Batas masuk ulang: koin yang sama paling banyak 1 + `max_reentries` kali per hari.

        Masuk ulang tepat saat harga berbalik bisa tertahan lama; batas ini membatasi berapa kali
        satu koin dikejar dalam sehari, short dan long dihitung bersama. Uji kertas dan uang
        sungguhan dihitung terpisah.
        """
        today = datetime.fromtimestamp(self._wall_clock()).date()
        real = live_orders_enabled()
        entered = sum(
            1
            for e in self._journal.load()
            if e.symbol == symbol
            and e.entry_price is not None
            and e.real == real
            and datetime.fromtimestamp(e.created_at).date() == today
        )
        limit = 1 + self.params.max_reentries
        if entered >= limit:
            return (
                f"sudah masuk {entered} kali hari ini (masuk ulang paling banyak "
                f"{self.params.max_reentries} kali per koin per hari)"
            )
        return None

    def momentum_sides(self, symbol: str) -> tuple[str, ...]:
        """Arah masuk ulang untuk koin yang baru terjual di target: arah posisi yang terjual itu
        (momentumnya searah), selama arah itu masih dipakai di pengaturan."""
        real = live_orders_enabled()
        sold = [
            e
            for e in self._journal.load()
            if e.symbol == symbol and e.status == "target" and e.real == real
        ]
        if not sold:
            return ()
        side = max(sold, key=lambda e: e.closed_at or 0.0).side
        return (side,) if self.params.side_enabled(side) else ()

    def recent_target_sales(self, within_s: float) -> dict[str, float]:
        """Pair yang terjual di target dalam `within_s` detik terakhir -> waktu terjualnya.

        Uji kertas dan uang sungguhan dipisah, sama seperti batas masuk ulang."""
        since = self._wall_clock() - within_s
        real = live_orders_enabled()
        sales: dict[str, float] = {}
        for e in self._journal.load():
            if e.status == "target" and e.real == real and e.closed_at and e.closed_at >= since:
                sales[e.symbol] = max(sales.get(e.symbol, 0.0), e.closed_at)
        return sales

    def has_open(self, symbol: str) -> bool:
        """Pair ini masih punya posisi terbuka (uji kertas atau sungguhan) di jurnal."""
        return any(e.symbol == symbol and e.status == "open" for e in self._journal.load())

    def _refresh_by_price(self) -> list[JournalEntry]:
        return refresh_by_price(
            self._journal, self._market, self.params.fee_pct, self._wall_clock(), self._nav
        )

    def slot_blocker(self) -> str | None:
        """Langkah 4 SOP: koin berikutnya hanya bila posisi yang terbuka tidak sedang rugi.

        Jumlah posisi tidak dibatasi (keputusan 15 Okt)."""
        opened = [e for e in self._journal.load() if e.status == "open"]
        for entry in opened:
            assert entry.entry_price is not None
            # Dibandingkan dengan sisi harga yang sama saat masuk (bid untuk short, ask untuk
            # long), supaya spread sesaat setelah masuk tidak dihitung sebagai rugi.
            try:
                price = entry_price_of(entry.side, self._market.quote(entry.symbol))
            except MarketDataError as exc:
                return f"harga {entry.symbol} tidak terbaca ({exc}); koin berikutnya ditahan"
            if gain_pct(entry, price) < 0:
                sign = "<" if entry.side == "long" else ">"
                return (
                    f"posisi {entry.symbol} sedang rugi ({price:g} {sign} masuk "
                    f"{entry.entry_price:g}); koin berikutnya belum boleh dibuka"
                )
        return None

    def trade(
        self,
        rank: int,
        symbol: str,
        reading_source: ReadingSource | None,
        sides: Sequence[str] | None = None,
    ) -> JournalEntry:
        """Jalankan langkah 2-5 SOP untuk pair yang halaman trade-nya sedang terbuka.

        `sides`: arah yang boleh dibuka; bawaan menurut Top (`params.sides_for(rank)`)."""
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_{symbol}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
            capital_usdt=self.params.capital_usdt,
            leverage=self.params.leverage,
            role=self._role,
        )
        try:
            self._run(
                entry, reading_source, self.params.sides_for(rank) if sides is None else sides
            )
        except (_Skip, BotError) as exc:
            entry.status = "skipped"
            entry.reason = str(exc)
        return self._finish(entry)

    def skip(
        self, rank: int, symbol: str, reason: str, reading: PatternReading | None = None
    ) -> JournalEntry:
        """Catat koin yang tidak dimasuki tanpa membuka aplikasi (mis. pola leader tidak OK)."""
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_{symbol}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
            status="skipped",
            reason=reason,
            capital_usdt=self.params.capital_usdt,
            leverage=self.params.leverage,
            role=self._role,
        )
        if reading is not None:
            self._record_reading(entry, reading)
            entry.verdict = self.decide(reading, rank).verdict
        return self._finish(entry)

    def decide(self, reading: PatternReading, rank: int) -> Decision:
        long = reading.long.pattern if reading.long is not None else None
        sides = self.params.sides_for(rank)
        return decide(reading.pattern, long, sides, self.params, self.profile)

    @staticmethod
    def _record_reading(entry: JournalEntry, reading: PatternReading) -> None:
        entry.pattern_ai = reading.pattern.as_dict()
        entry.ai_summary = reading.summary
        if reading.long is not None:
            entry.long_ai = {**reading.long.pattern.as_dict(), "summary": reading.long.summary}

    def _ensure_leverage(self, leverage: int) -> MarginSettings:
        """Bot mengubah leverage koin ke SOP (2x) sebelum mengisi form. Bila bursa menolak
        (mis. akun Futures belum aktif), uji kertas tetap berjalan dengan peringatan."""
        try:
            return self._nav.ensure_leverage(leverage)
        except ScreenReadError as exc:
            logger.warning("Leverage tidak bisa diubah ke %dx: %s", leverage, exc)
            try:
                return self._nav.read_margin_settings()
            except ScreenReadError:
                return MarginSettings(isolated=None, leverage=None)

    def note(self, rank: int, reason: str, symbol: str = "-") -> None:
        """Tampilkan Top yang TIDAK diproses di aplikasi, beserta alasannya.

        Hanya kejadian untuk tabel "Putaran ini": tidak masuk jurnal, tidak membuka aplikasi, dan
        tidak bertanya ke hub. Tanpa ini tabel pengikut hanya berisi Top yang sempat diproses.
        """
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_top{rank}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
            status="skipped",
            reason=reason,
            role=self._role,
        )
        logger.info("#%d tidak diproses: %s", rank, reason, extra=coin_event(entry, self.params))

    def _finish(self, entry: JournalEntry) -> JournalEntry:
        rank, symbol = entry.rank, entry.symbol
        self._journal.append(entry)
        if entry.status == "open":
            logger.info(
                "#%d %s dicatat di jurnal: posisi %s terbuka",
                rank,
                symbol,
                "uang sungguhan" if entry.real else "uji",
                extra=coin_event(entry, self.params),
            )
        else:
            logger.info(
                "#%d %s tidak masuk: %s",
                rank,
                symbol,
                entry.reason,
                extra=coin_event(entry, self.params),
            )
        return entry

    def _run(
        self, entry: JournalEntry, reading_source: ReadingSource | None, sides: Sequence[str]
    ) -> None:
        params, symbol = self.params, entry.symbol
        if not sides:
            raise _Skip("Top ini tidak dipilih untuk short maupun long")
        if not symbol.endswith("USDT"):
            raise _Skip("bukan pair USDT")
        # Dicek sebelum grafik dan AI: tidak perlu membaca koin yang memang tidak akan dimasuki.
        reentry = self.reentry_blocker(symbol)
        if reentry:
            raise _Skip(reentry)

        # Harga dan spread dibaca sekarang; kenaikan minimal bila diisi gugur di sini. Spread baru
        # menolak koin SETELAH pola dinilai (urutan SOP: pola, biaya, slot), supaya penilaian AI dan
        # grafiknya tetap tampil untuk koin yang spread-nya lebar. Funding rate tidak dinilai.
        quote = self._market.quote(symbol)
        entry.change_pct = quote.change_pct
        entry.spread_pct = quote.spread_pct
        if quote.change_pct < params.min_gain_pct:
            raise _Skip(f"naik {quote.change_pct:.1f}% < {params.min_gain_pct:g}% dalam 24 jam")
        cost_issue: str | None = None
        if quote.spread_pct > params.max_spread_pct:
            cost_issue = f"spread {quote.spread_pct:.3f}% > {params.max_spread_pct:g}%"

        # Saringan pola: garis kuning (MA7) terhadap MA25 di chart 15 menit.
        self._nav.show_15m_chart()
        name = f"{entry.id}_rank{entry.rank}"
        shots = self._settings.screenshot_dir
        entry.screenshots.append(str(self._nav.capture_window(shots / f"{name}.png")))
        chart = self._nav.capture_chart(shots / f"{name}_15m.png")
        entry.screenshots.append(str(chart))

        long_wanted = "long" in sides
        try:
            profile = self.profile
            klines = self._market.klines(symbol, "15m", limit=candles_needed(mid=profile.mid))
            data: MaPattern | None = data_ma_pattern(
                klines, fast=profile.fast, mid=profile.mid, recent=profile.recent_candles
            )
            # V3: jarak kedua garis dicatat tiap koin (angka batas "berjauhan" belum ditetapkan).
            entry.ma_gap_pct = ma_gap_pct(klines, fast=profile.fast, mid=profile.mid)
        except MarketDataError as exc:  # bursa tanpa sumber candle: hanya AI yang menilai
            logger.info("Pembanding data tidak ada: %s", exc)
            data = None
        if long_wanted and data is not None:
            try:  # V4: angka tanda LONG dicatat (ambangnya belum ditetapkan)
                entry.long_data = long_numbers(klines)
            except ValueError as exc:
                logger.info("Angka MA untuk LONG belum bisa dihitung: %s", exc)
        entry.pattern_data = data.as_dict() if data else None
        decisive = data
        long: LongPattern | None = None
        if params.signal_source == "ai":
            if reading_source is None:
                raise _Skip("SINYAL=ai tetapi tidak ada sumber analisis AI")
            reading = reading_source(symbol, chart, long_wanted)
            self._record_reading(entry, reading)
            decisive = reading.pattern
            long = reading.long.pattern if reading.long is not None else None
        if decisive is None:
            raise _Skip("bursa ini tidak punya data candle; pakai SINYAL=ai")
        decision = decide(decisive, long, sides, params, self.profile)
        short_verdict = self.profile.verdict(decisive, params.min_crosses)
        entry.verdict = decision.verdict
        logger.info(
            "#%d %s garis kuning %s: %d kali di bawah MA%d -> %s (data: %d kali)%s",
            entry.rank,
            symbol,
            params.signal_source.upper(),
            decisive.below_count,
            self.profile.mid,
            _VERDICT_TEXT[short_verdict],
            data.below_count if data else -1,
            f" | {entry.ai_summary}" if entry.ai_summary else "",
        )
        if long_wanted:
            logger.info(
                "#%d %s tanda LONG AI: %s%s",
                entry.rank,
                symbol,
                (signs_text(long.signs) or "tidak ada") if long is not None else "tidak terbaca",
                f" | {entry.long_ai['summary']}" if entry.long_ai else "",
            )
        if decision.side is None:
            raise _Skip(decision.reason)
        side = decision.side
        if side == "long" and long is not None:
            entry.long_signs = long.signs

        # Langkah 3 SOP (setelah pola): spread.
        if cost_issue:
            raise _Skip(cost_issue)

        # Langkah 4 SOP: pair yang sama dan slot posisi.
        if any(e.symbol == symbol and e.status == "open" for e in self._journal.load()):
            raise _Skip("sudah ada posisi uji yang masih terbuka untuk pair ini")
        blocker = self.slot_blocker()
        if blocker:
            raise _Skip(blocker)

        # Ukuran posisi: margin % modal x leverage.
        if params.capital_share is not None:
            params = self._capital_from_balance(entry, params.capital_share)
        rules = self._market.rules(symbol)
        price = entry_price_of(side, quote)  # short menjual ke bid, long membeli di ask
        sizing = size_position(params, price, rules, self._settings.decimal_separator)
        if isinstance(sizing, str):
            raise _Skip(sizing)
        if live_orders_enabled():
            self._require_balance(sizing.margin_usdt)

        if self._fill_form:
            margin = self._ensure_leverage(params.leverage)
        else:
            margin = self._nav.read_margin_settings()
        entry.margin = margin.describe()
        issues = margin.problems(params.leverage)
        for issue in issues:
            logger.warning("Margin di aplikasi: %s. Wajib diubah sebelum order sungguhan.", issue)
        if issues and live_orders_enabled():
            # Uang sungguhan: leverage yang tidak terbukti 2x (salah atau tidak terbaca) = tidak
            # masuk. Uji nyata 21 Okt: leverage tidak terbaca, order tetap dikirim dan terbuka 20x.
            raise _Skip(f"order sungguhan tidak dikirim: {issues[0]} (leverage harus terbukti 2x)")

        # Langkah 5: isi form lalu pintu order (dimatikan).
        if self._fill_form:
            self._nav.fill_quantity(sizing.order_text)
        toward = 1 if side == "long" else -1  # arah harga yang menguntungkan posisi
        target_pct = params.target_for(side)
        plan = OrderPlan(
            symbol=symbol,
            order_text=sizing.order_text,
            quantity_text=sizing.quantity_text,
            notional=sizing.notional,
            margin_usdt=sizing.margin_usdt,
            entry_price=price,
            target_price=price * (1 + toward * target_pct / 100),
            leverage=params.leverage,
            side=side.upper(),
            cutloss_price=(
                price * (1 - toward * params.stop_pct / 100) if params.stop_pct else None
            ),
            margin_mode=margin.mode,
        )
        self._gate.submit(plan)

        now_s = self._wall_clock()
        entry.status = "open"
        entry.side = side
        entry.real = live_orders_enabled()  # tombol order ditekan sungguhan
        entry.entry_price = plan.entry_price
        entry.max_price = plan.entry_price
        entry.min_price = plan.entry_price
        # Harga terakhir terbaca (harga tutup posisi): bahan daftar Posisi tanpa layar.
        entry.last_price = quote.bid if side == "long" else quote.ask
        entry.last_price_at = now_s
        entry.quantity = sizing.quantity
        entry.notional = sizing.notional
        entry.margin_usdt = sizing.margin_usdt
        entry.target_price = plan.target_price
        entry.cutloss_price = plan.cutloss_price
        if params.time_limit:
            entry.green_exit_at = now_s + HOLD_GREEN_H * 3600
            entry.time_exit_at = now_s + HOLD_MAX_H * 3600
        exits = []
        if plan.cutloss_price is not None:
            exits.append(f"cutloss di {plan.cutloss_price:g} ({params.stop_pct:g}%)")
        else:
            exits.append("tanpa stop-loss")
        if params.time_limit:
            exits.append(
                f"jual sesudah {HOLD_GREEN_H:g} jam bila untung, paling lama {HOLD_MAX_H:g} jam"
            )
        else:
            exits.append("tanpa batas waktu")
        logger.info(
            "#%d %s MASUK %s: %s %s USDT @ %g (%dx, margin %.2f USDT) | jual otomatis "
            "di %g (%s %g%%), %s",
            entry.rank,
            symbol,
            "UANG SUNGGUHAN" if entry.real else "UJI KERTAS",
            side,
            sizing.order_text,
            price,
            params.leverage,
            sizing.margin_usdt,
            plan.target_price,
            "naik" if side == "long" else "turun",
            target_pct,
            " dan ".join(exits),
        )
