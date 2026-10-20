"""Konfigurasi bot. Nilai default bisa ditimpa lewat environment variable `BOT_*` atau `.env`."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "BOT_"
# macOS: bundle id. Windows: nama file exe.
DEFAULT_APP_ID = "Binance.exe" if sys.platform == "win32" else "com.binance.BinanceDesktop"


def read_dotenv(path: Path) -> dict[str, str]:
    """Baca file `.env` sederhana (baris KEY=VALUE). File yang tidak ada dianggap kosong."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    # Aplikasi
    app_name: str = "Binance"
    app_bundle_id: str = DEFAULT_APP_ID
    launch_timeout_s: float = 20.0
    poll_interval_s: float = 0.5
    settle_delay_s: float = 2.0
    # Keluaran
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    screenshot_dir: Path = Path("screenshots")
    journal_path: Path = Path("journal/sop.jsonl")
    # Giliran layar dibagi semua bot di laptop ini (lihat filelock.ScreenTurn). None = tanpa giliran
    # (tes); dari environment selalu berisi file di folder sementara pengguna.
    screen_lock_path: Path | None = None
    # Tanda desimal saat mengetik di kolom Jumlah (Binance bahasa Indonesia memakai koma).
    decimal_separator: str = ","
    # Analisis AI
    analyzer_model: str = "anthropic/haiku-5.5"
    analyzer_timeout_s: float = 60.0
    # Hidup: lebih akurat membaca bentuk candle (sekitar 10 detik). Mati: sekitar 6 detik.
    analyzer_thinking: bool = True
    # Leader memakai ulang analisis koin yang sama selama ini, tanpa memanggil AI lagi.
    analysis_ttl_s: float = 900.0
    vikey_api_base: str = ""
    # Rahasia: jangan ikut tercetak di log atau traceback.
    vikey_api_key: str = field(default="", repr=False)
    # Hub LAN (mode banyak)
    hub_url: str = ""
    hub_port: int = 8765
    hub_token: str = field(default="", repr=False)
    follower_wait_s: float = 300.0  # leader menilai Top 1..5 berurutan, sekitar 30 detik per koin

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        defaults = cls()

        def get(key: str, default: object) -> str:
            return env.get(f"{ENV_PREFIX}{key}", str(default))

        return cls(
            app_name=get("APP_NAME", defaults.app_name),
            app_bundle_id=get("APP_BUNDLE_ID", defaults.app_bundle_id),
            launch_timeout_s=float(get("LAUNCH_TIMEOUT_S", defaults.launch_timeout_s)),
            poll_interval_s=float(get("POLL_INTERVAL_S", defaults.poll_interval_s)),
            settle_delay_s=float(get("SETTLE_DELAY_S", defaults.settle_delay_s)),
            log_level=get("LOG_LEVEL", defaults.log_level).upper(),
            log_dir=Path(get("LOG_DIR", defaults.log_dir)),
            screenshot_dir=Path(get("SCREENSHOT_DIR", defaults.screenshot_dir)),
            journal_path=Path(get("JOURNAL_PATH", defaults.journal_path)),
            screen_lock_path=Path(
                get("SCREEN_LOCK_PATH", Path(tempfile.gettempdir()) / "marketforge-screen.lock")
            ),
            decimal_separator=get("DECIMAL_SEPARATOR", defaults.decimal_separator),
            analyzer_model=get("ANALYZER_MODEL", defaults.analyzer_model),
            analyzer_timeout_s=float(get("ANALYZER_TIMEOUT_S", defaults.analyzer_timeout_s)),
            analyzer_thinking=get("ANALYZER_THINKING", "true").lower()
            not in ("0", "false", "no", "off"),
            analysis_ttl_s=float(get("ANALYSIS_TTL_S", defaults.analysis_ttl_s)),
            vikey_api_base=env.get("VIKEY_API_BASE", defaults.vikey_api_base),
            vikey_api_key=env.get("VIKEY_API_KEY", defaults.vikey_api_key),
            hub_url=get("HUB_URL", defaults.hub_url),
            hub_port=int(get("HUB_PORT", defaults.hub_port)),
            hub_token=get("HUB_TOKEN", defaults.hub_token),
            follower_wait_s=float(get("FOLLOWER_WAIT_S", defaults.follower_wait_s)),
        )
