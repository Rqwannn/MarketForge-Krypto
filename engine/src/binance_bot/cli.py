from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from binance_bot import __version__
from binance_bot.analysis import ConsensusAnalyzer, VikeyPatternAnalyzer
from binance_bot.analysis.pattern import PROMPT, TEBBIT_PROMPT
from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.binance_desktop.layout import MAX_RANK
from binance_bot.config import Settings, read_dotenv
from binance_bot.exceptions import BotError
from binance_bot.hub import AnalysisStore, HubClient, HubServer
from binance_bot.logging_setup import setup_logging
from binance_bot.macos.keyboard import NUMBER_PATTERN
from binance_bot.market import FuturesMarket, MarketData
from binance_bot.strategy import DryRunOrderGate, Journal, SopParams
from binance_bot.strategy.params import SIGNAL_SOURCES
from binance_bot.system import System, build_system
from binance_bot.tebbit_web.chrome import ChromeController, ChromeWindowController
from binance_bot.tebbit_web.market import ScreenMarket
from binance_bot.tebbit_web.navigator import TebbitNavigator
from binance_bot.workflows import (
    ExampleWorkflow,
    FillTestWorkflow,
    FollowerWorkflow,
    HistoryWorkflow,
    JournalWorkflow,
    LeaderWorkflow,
    OpenBinanceWorkflow,
    PositionsWorkflow,
    ReadinessWorkflow,
    SingleWorkflow,
    SopTrader,
    WindowSizeWorkflow,
    Workflow,
)
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.positions import ALL

logger = logging.getLogger(__name__)
_DEFAULTS = SopParams()
ALL_RANKS = list(range(1, MAX_RANK + 1))  # SOP V2: pantau top 5


def parse_number(text: str) -> str:
    """Angka yang akan diketik apa adanya, mis. "1" atau "184,6"."""
    if not NUMBER_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError("hanya angka, mis. 1 atau 1,5")
    return text


def parse_rank(text: str) -> int:
    try:
        rank = int(text)
    except ValueError:
        rank = 0
    if not 1 <= rank <= MAX_RANK:
        raise argparse.ArgumentTypeError(f"rank harus angka 1..{MAX_RANK}")
    return rank


def parse_ranks(text: str) -> list[int]:
    """ "1,2,3" -> [1, 2, 3], tanpa duplikat dan urutan dipertahankan."""
    ranks = [parse_rank(part.strip()) for part in text.split(",") if part.strip()]
    if not ranks:
        raise argparse.ArgumentTypeError("isi minimal satu rank, mis. 1,2,3")
    return list(dict.fromkeys(ranks))


def _sop_options() -> argparse.ArgumentParser:
    """Parameter SOP V2. Default = angka di PDF; yang bertanda usulan perlu disepakati."""
    d = _DEFAULTS
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("parameter SOP V2")
    g.add_argument("--modal", type=float, help="Modal USDT")
    g.add_argument(
        "--jumlah", type=float, help="Ukuran order manual dalam USDT (menimpa margin x leverage)"
    )
    g.add_argument("--margin", type=float, default=d.margin_pct, help="Margin %% modal per posisi")
    g.add_argument("--leverage", type=int, default=d.leverage, help="Leverage")
    g.add_argument("--sl", type=float, default=d.stop_pct, help="Stop-loss %% di atas harga masuk")
    g.add_argument("--target", type=float, default=d.target_pct, help="Target %% turun (1-4)")
    g.add_argument(
        "--min-turun",
        type=int,
        default=d.min_crosses,
        help="Minimal berapa kali MA7 di bawah MA25 agar pola OK",
    )
    g.add_argument(
        "--min-naik",
        type=float,
        default=d.min_gain_pct,
        help="Naik minimal 24 jam (%%); 0 = tidak disaring",
    )
    g.add_argument("--batas-jam", type=float, default=d.max_hold_h, help="Tutup setelah N jam")
    g.add_argument("--biaya", type=float, default=d.fee_pct, help="Fee per putaran (%%)")
    g.add_argument(
        "--maks-spread", type=float, default=d.max_spread_pct, help="Spread maksimal (%%)"
    )
    g.add_argument(
        "--min-funding", type=float, default=d.min_funding_pct, help="Funding minimal (%%)"
    )
    g.add_argument(
        "--maks-posisi",
        type=int,
        default=d.max_open_positions,
        help="Posisi terbuka maksimal bersamaan",
    )
    g.add_argument(
        "--sinyal",
        choices=SIGNAL_SOURCES,
        default=d.signal_source,
        help="Pembaca pola garis kuning: ai (screenshot) atau data (candle)",
    )
    g.add_argument("--no-fill", action="store_true", help="Jangan isi kolom Jumlah di aplikasi")
    return p


def params_from(args: argparse.Namespace) -> SopParams:
    return SopParams(
        capital_usdt=args.modal,
        order_usdt=args.jumlah,
        margin_pct=args.margin,
        leverage=args.leverage,
        stop_pct=args.sl,
        target_pct=args.target,
        min_crosses=args.min_turun,
        min_gain_pct=args.min_naik,
        max_hold_h=args.batas_jam,
        fee_pct=args.biaya,
        max_spread_pct=args.maks_spread,
        min_funding_pct=args.min_funding,
        max_open_positions=args.maks_posisi,
        signal_source=args.sinyal,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="binance-bot",
        description="Engine SOP V2 Short Top Gainers (Futures 2x) untuk Binance Desktop. "
        "Tombol order TIDAK pernah ditekan (dry run).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR (menimpa BOT_LOG_LEVEL)")
    parser.add_argument(
        "--events", action="store_true", help="Log sebagai JSON per baris di stdout (aplikasi)"
    )
    parser.add_argument(
        "--bursa",
        choices=BURSA,
        default="binance",
        help="Platform: binance (aplikasi desktop) atau tebbit (website di Chrome)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sop = _sop_options()

    sub.add_parser("open", help="Buka aplikasi Binance hanya jika belum berjalan.")

    size = sub.add_parser("window-size", help="Cek ukuran jendela Binance terhadap kalibrasi.")
    size.add_argument(
        "--atur", action="store_true", help="Atur ukuran jendela ke ukuran kalibrasi (Windows)"
    )

    single = sub.add_parser("single", parents=[sop], help="Satu laptop: SOP penuh, AI sendiri.")
    single.add_argument("--ranks", type=parse_ranks, default=ALL_RANKS, help="Rank, mis. 1,2,3")
    single.add_argument("--interval", type=float, default=0.0, help="Pantau ulang tiap N menit")

    leader = sub.add_parser(
        "leader", help="Mode banyak: AI pola garis kuning sekali per koin, lewat hub."
    )
    leader.add_argument("--ranks", type=parse_ranks, default=ALL_RANKS, help="Rank, mis. 1,2,3")
    leader.add_argument(
        "--min-naik",
        type=float,
        default=_DEFAULTS.min_gain_pct,
        help="Naik minimal 24 jam (%%) agar dianalisis AI; 0 = semua",
    )
    leader.add_argument(
        "--min-turun",
        type=int,
        default=_DEFAULTS.min_crosses,
        help="Ambang pola OK (hanya untuk log leader)",
    )
    leader.add_argument("--interval", type=float, default=0.0, help="Ulangi tiap N menit")
    leader.add_argument("--port", type=int, help="Port hub (menimpa BOT_HUB_PORT)")

    follower = sub.add_parser(
        "follower", parents=[sop], help="Mode banyak: SOP penuh dengan hasil AI dari hub leader."
    )
    follower.add_argument("--hub", help="Alamat hub leader, mis. http://192.168.1.10:8765")
    follower.add_argument("--rank", type=parse_rank, default=1, help="Top gainer ke berapa")
    follower.add_argument(
        "--ranks", type=parse_ranks, help="Beberapa Top sekaligus, mis. 2,4,5 (menimpa --rank)"
    )
    follower.add_argument(
        "--semua",
        action="store_true",
        help="Ikuti semua Top yang dimainkan leader di putaran ini (menimpa --rank)",
    )

    jurnal = sub.add_parser(
        "jurnal", parents=[sop], help="Nilai uji kertas dan rekap terhadap titik impas."
    )
    jurnal.add_argument("--json", action="store_true", help="Cetak rekap sebagai JSON di stdout")

    positions = sub.add_parser(
        "posisi", parents=[sop], help="Posisi uji kertas terbuka (JSON); --tutup untuk Sell."
    )
    positions.add_argument(
        "--tutup", help="Tutup (uji kertas) posisi pair ini, atau 'semua'", metavar="PAIR"
    )

    sub.add_parser(
        "cek", help="Cek kesiapan laptop (izin, Binance, jendela, API, .env) dalam JSON."
    )

    fill = sub.add_parser(
        "uji-isi", help="Uji kalibrasi: buka top gainer lalu isi kolom Jumlah (tanpa order)."
    )
    fill.add_argument("--rank", type=parse_rank, default=1, help="Top gainer ke berapa")
    fill.add_argument(
        "--jumlah", type=parse_number, required=True, help="Ukuran order USDT, mis. 5 atau 5,5"
    )

    history = sub.add_parser("riwayat", help="Hapus riwayat analisis AI (JSON).")
    what = history.add_mutually_exclusive_group(required=True)
    what.add_argument("--hapus", metavar="ID", help="Hapus satu entri riwayat")
    what.add_argument(
        "--bersihkan", action="store_true", help="Hapus semua yang bukan trade (dilewati, contoh)"
    )

    example = sub.add_parser(
        "contoh", help="AI menilai gambar grafik 15 menit (PNG); hasilnya masuk riwayat analisis."
    )
    example.add_argument("gambar", type=Path, help="File PNG grafik 15 menit")
    example.add_argument("--koin", required=True, help="Pair, mis. MAGICUSDT")
    example.add_argument("--catatan", default="", help="Mis. penilaian Pak Saputra")
    return parser


BURSA = ("binance", "tebbit")
TEBBIT_JOURNAL = Path("journal/sop-tebbit.jsonl")
TEBBIT_COMMANDS = (
    "single",
    "leader",
    "follower",
    "jurnal",
    "posisi",
    "uji-isi",
    "contoh",
    "riwayat",
)


def build_tebbit(settings: Settings, system: System) -> tuple[TradingNavigator, MarketData]:
    chrome = ChromeController()
    navigator = TebbitNavigator(
        settings,
        system.apps,
        ChromeWindowController(chrome),
        system.reader,
        chrome,
        screens=system.screens,
    )
    return navigator, ScreenMarket(navigator)


def build_workflow(args: argparse.Namespace, settings: Settings) -> Workflow:
    system = build_system(settings)
    apps = system.apps
    tebbit = args.bursa == "tebbit"
    if tebbit and args.command not in TEBBIT_COMMANDS:
        raise BotError(f"Perintah '{args.command}' belum tersedia untuk Tebbit")
    if tebbit and settings.journal_path == Settings().journal_path:
        settings = replace(settings, journal_path=TEBBIT_JOURNAL)  # jurnal terpisah per bursa
    if args.command == "open":
        return OpenBinanceWorkflow(settings, apps)
    if args.command == "window-size":
        return WindowSizeWorkflow(settings, system.window, resize=args.atur)

    window = system.window
    navigator: TradingNavigator
    market: MarketData
    if tebbit:
        navigator, market = build_tebbit(settings, system)
    else:
        market = FuturesMarket()
    if args.command == "cek":
        return ReadinessWorkflow(
            settings,
            apps,
            window,
            market,
            accessibility=system.accessibility_allowed,
            screen_capture=system.screen_capture_allowed,
            screens=system.screens,
        )
    journal = Journal(settings.journal_path)
    if args.command == "jurnal":
        return JournalWorkflow(params_from(args), journal, market, as_json=args.json)
    if args.command == "riwayat":
        return HistoryWorkflow(journal, delete_id=args.hapus, clear=args.bersihkan)
    if args.command == "contoh":
        return ExampleWorkflow(
            args.gambar,
            args.koin,
            args.catatan,
            ConsensusAnalyzer(
                VikeyPatternAnalyzer(settings, prompt=TEBBIT_PROMPT if tebbit else PROMPT)
            ),
            journal,
            settings.screenshot_dir,
            SopParams(),
        )
    if args.command == "posisi":
        target = args.tutup.upper() if args.tutup and args.tutup.lower() != ALL else args.tutup
        return PositionsWorkflow(params_from(args), journal, market, close=target)

    if not tebbit:
        navigator = BinanceNavigator(settings, apps, window, system.reader, screens=system.screens)
    if args.command == "uji-isi":
        return FillTestWorkflow(navigator, rank=args.rank, quantity_text=args.jumlah)
    if args.command == "leader":
        store = AnalysisStore()
        return LeaderWorkflow(
            settings,
            SopParams(min_gain_pct=args.min_naik, min_crosses=args.min_turun),
            navigator,
            market,
            ConsensusAnalyzer(
                VikeyPatternAnalyzer(settings, prompt=TEBBIT_PROMPT if tebbit else PROMPT)
            ),
            store,
            HubServer(store, settings.hub_token, port=args.port or settings.hub_port),
            args.ranks,
            interval_s=args.interval * 60,
        )

    params = params_from(args)
    trader = SopTrader(
        settings,
        params,
        navigator,
        market,
        journal,
        DryRunOrderGate(),
        fill_form=not args.no_fill,
        role="follower" if args.command == "follower" else "single",
    )
    uses_ai = params.signal_source == "ai"
    if args.command == "single":
        analyzer = (
            ConsensusAnalyzer(
                VikeyPatternAnalyzer(settings, prompt=TEBBIT_PROMPT if tebbit else PROMPT)
            )
            if uses_ai
            else None
        )
        return SingleWorkflow(
            navigator, trader, analyzer, ranks=args.ranks, interval_s=args.interval * 60
        )
    if args.command == "follower":
        client = HubClient(args.hub or settings.hub_url, settings.hub_token) if uses_ai else None
        return FollowerWorkflow(
            settings,
            navigator,
            trader,
            client,
            ranks=None if args.semua else (args.ranks or [args.rank]),
        )
    raise ValueError(f"Command tidak dikenal: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Variabel lingkungan menang atas isi `.env`.
    settings = Settings.from_env({**read_dotenv(Path(".env")), **os.environ})
    setup_logging(
        args.log_level.upper() if args.log_level else settings.log_level,
        settings.log_dir,
        events=args.events,
    )

    try:
        build_workflow(args, settings).run()
    except BotError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Dihentikan oleh pengguna")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
