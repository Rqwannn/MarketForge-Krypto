from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from binance_bot import __version__
from binance_bot.analysis import VikeyPeakAnalyzer
from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.binance_desktop.layout import MAX_RANK
from binance_bot.config import Settings, read_dotenv
from binance_bot.exceptions import BotError
from binance_bot.hub import AnalysisStore, HubClient, HubServer
from binance_bot.logging_setup import setup_logging
from binance_bot.macos.keyboard import NUMBER_PATTERN
from binance_bot.market import FuturesMarket
from binance_bot.strategy import DryRunOrderGate, Journal, SopParams
from binance_bot.strategy.params import SIGNAL_SOURCES
from binance_bot.system import build_system
from binance_bot.workflows import (
    FillTestWorkflow,
    FollowerWorkflow,
    JournalWorkflow,
    LeaderWorkflow,
    OpenBinanceWorkflow,
    SingleWorkflow,
    SopTrader,
    WindowSizeWorkflow,
    Workflow,
)

logger = logging.getLogger(__name__)
_DEFAULTS = SopParams()


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
    """Parameter SOP. Default = angka di PDF; yang bertanda usulan perlu disepakati."""
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("parameter SOP")
    g.add_argument("--modal", type=float, help="Modal USDT untuk rumus ukuran posisi")
    g.add_argument("--jumlah", type=float, help="Jumlah koin manual (menimpa rumus)")
    g.add_argument("--risiko", type=float, default=_DEFAULTS.risk_pct, help="%% modal per trade")
    g.add_argument(
        "--sl", type=float, default=_DEFAULTS.stop_pct, help="Stop-loss %% di atas masuk"
    )
    g.add_argument(
        "--target", type=float, default=_DEFAULTS.target_pct, help="Target %% di bawah masuk"
    )
    g.add_argument(
        "--min-naik", type=float, default=_DEFAULTS.min_gain_pct, help="Naik minimal 24 jam (%%)"
    )
    g.add_argument(
        "--min-tanda", type=int, default=_DEFAULTS.min_signs, help="Tanda pucuk minimal (dari 4)"
    )
    g.add_argument(
        "--batas-jam", type=float, default=_DEFAULTS.max_hold_h, help="Tutup setelah N jam"
    )
    g.add_argument(
        "--biaya", type=float, default=_DEFAULTS.fee_pct, help="Biaya total per trade (%%)"
    )
    g.add_argument(
        "--maks-spread", type=float, default=_DEFAULTS.max_spread_pct, help="Spread maksimal (%%)"
    )
    g.add_argument(
        "--min-funding", type=float, default=_DEFAULTS.min_funding_pct, help="Funding minimal (%%)"
    )
    g.add_argument(
        "--maks-posisi", type=int, default=_DEFAULTS.max_positions, help="Posisi uji baru per jalan"
    )
    g.add_argument(
        "--sinyal",
        choices=SIGNAL_SOURCES,
        default=_DEFAULTS.signal_source,
        help="Penentu tanda pucuk: ai (screenshot) atau data (candle)",
    )
    g.add_argument("--no-fill", action="store_true", help="Jangan isi kolom Jumlah di aplikasi")
    return p


def params_from(args: argparse.Namespace) -> SopParams:
    return SopParams(
        capital_usdt=args.modal,
        quantity=args.jumlah,
        risk_pct=args.risiko,
        stop_pct=args.sl,
        target_pct=args.target,
        min_gain_pct=args.min_naik,
        min_signs=args.min_tanda,
        max_hold_h=args.batas_jam,
        fee_pct=args.biaya,
        max_spread_pct=args.maks_spread,
        min_funding_pct=args.min_funding,
        max_positions=args.maks_posisi,
        signal_source=args.sinyal,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="binance-bot",
        description="Engine SOP Short Top Gainers (Futures 1x) untuk Binance Desktop. "
        "Tombol order TIDAK pernah ditekan (dry run).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR (menimpa BOT_LOG_LEVEL)")
    sub = parser.add_subparsers(dest="command", required=True)
    sop = _sop_options()

    sub.add_parser("open", help="Buka aplikasi Binance hanya jika belum berjalan.")

    size = sub.add_parser("window-size", help="Cek ukuran jendela Binance terhadap kalibrasi.")
    size.add_argument(
        "--atur", action="store_true", help="Atur ukuran jendela ke ukuran kalibrasi (Windows)"
    )

    single = sub.add_parser("single", parents=[sop], help="Satu laptop: SOP penuh, AI sendiri.")
    single.add_argument("--ranks", type=parse_ranks, default=[1, 2, 3], help="Rank, mis. 1,2,3")

    leader = sub.add_parser(
        "leader", help="Mode banyak: AI tanda pucuk sekali per koin, lewat hub."
    )
    leader.add_argument("--ranks", type=parse_ranks, default=[1, 2, 3], help="Rank, mis. 1,2,3")
    leader.add_argument(
        "--min-naik",
        type=float,
        default=_DEFAULTS.min_gain_pct,
        help="Naik minimal 24 jam (%%) agar dianalisis AI",
    )
    leader.add_argument("--interval", type=float, default=0.0, help="Ulangi tiap N menit")
    leader.add_argument("--port", type=int, help="Port hub (menimpa BOT_HUB_PORT)")

    follower = sub.add_parser(
        "follower", parents=[sop], help="Mode banyak: SOP penuh dengan hasil AI dari hub leader."
    )
    follower.add_argument("--hub", help="Alamat hub leader, mis. http://192.168.1.10:8765")
    follower.add_argument("--rank", type=parse_rank, default=1, help="Top gainer ke berapa")

    sub.add_parser("jurnal", parents=[sop], help="Nilai uji kertas dan rekap terhadap titik impas.")

    fill = sub.add_parser(
        "uji-isi", help="Uji kalibrasi: buka top gainer lalu isi kolom Jumlah (tanpa order)."
    )
    fill.add_argument("--rank", type=parse_rank, default=1, help="Top gainer ke berapa")
    fill.add_argument("--jumlah", type=parse_number, required=True, help="Angka, mis. 1 atau 1,5")
    return parser


def build_workflow(args: argparse.Namespace, settings: Settings) -> Workflow:
    system = build_system(settings)
    apps = system.apps
    if args.command == "open":
        return OpenBinanceWorkflow(settings, apps)
    if args.command == "window-size":
        return WindowSizeWorkflow(settings, system.window, resize=args.atur)

    market = FuturesMarket()
    journal = Journal(settings.journal_path)
    if args.command == "jurnal":
        return JournalWorkflow(params_from(args), journal, market)

    navigator = BinanceNavigator(settings, apps, system.window, system.reader)
    if args.command == "uji-isi":
        return FillTestWorkflow(navigator, rank=args.rank, quantity_text=args.jumlah)
    if args.command == "leader":
        store = AnalysisStore()
        return LeaderWorkflow(
            settings,
            SopParams(min_gain_pct=args.min_naik),
            navigator,
            market,
            VikeyPeakAnalyzer(settings),
            store,
            HubServer(store, settings.hub_token, port=args.port or settings.hub_port),
            args.ranks,
            interval_s=args.interval * 60,
        )

    params = params_from(args)
    trader = SopTrader(
        settings, params, navigator, market, journal, DryRunOrderGate(), fill_form=not args.no_fill
    )
    uses_ai = params.signal_source == "ai"
    if args.command == "single":
        analyzer = VikeyPeakAnalyzer(settings) if uses_ai else None
        return SingleWorkflow(navigator, trader, analyzer, ranks=args.ranks)
    if args.command == "follower":
        client = HubClient(args.hub or settings.hub_url, settings.hub_token) if uses_ai else None
        return FollowerWorkflow(settings, navigator, trader, client, rank=args.rank)
    raise ValueError(f"Command tidak dikenal: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Variabel lingkungan menang atas isi `.env`.
    settings = Settings.from_env({**read_dotenv(Path(".env")), **os.environ})
    setup_logging(
        args.log_level.upper() if args.log_level else settings.log_level, settings.log_dir
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
