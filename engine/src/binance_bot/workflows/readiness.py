from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass

from binance_bot.binance_desktop.layout import window_size_problem
from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.macos import AppController, WindowController
from binance_bot.market import FuturesMarket

_PRIVACY = "System Settings > Privacy & Security"


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    ok: bool
    pesan: str
    wajib: bool = True  # False: hanya dibutuhkan sebagian mode


class ReadinessWorkflow:
    """Cek kesiapan laptop sebelum menjalankan SOP. Tidak mengklik apa pun.

    Keluaran satu JSON (dibaca aplikasi desktop). Nilai rahasia tidak pernah dicetak.
    """

    name = "cek"

    def __init__(
        self,
        settings: Settings,
        apps: AppController,
        window: WindowController,
        market: FuturesMarket,
        *,
        accessibility: Callable[[], bool],
        screen_capture: Callable[[], bool],
        output: Callable[[str], None] = print,
    ) -> None:
        self._settings = settings
        self._apps = apps
        self._window = window
        self._market = market
        self._accessibility = accessibility
        self._screen_capture = screen_capture
        self._output = output

    def run(self) -> None:
        checks = self.checks()
        result = {
            "ok": all(c.ok for c in checks if c.wajib),
            "checks": [asdict(c) for c in checks],
        }
        self._output(json.dumps(result, ensure_ascii=False))

    def checks(self) -> list[Check]:
        s = self._settings
        return [
            _flag(
                "accessibility",
                self._accessibility(),
                "Izin Accessibility aktif.",
                f"Izin Accessibility belum aktif. Aktifkan di {_PRIVACY} > Accessibility.",
            ),
            _flag(
                "screen",
                self._screen_capture(),
                "Izin rekam layar aktif.",
                f"Izin rekam layar belum aktif. Aktifkan di {_PRIVACY} > "
                "Screen & System Audio Recording.",
            ),
            *self._binance_checks(),
            self._api_check(),
            _flag(
                "ai_key",
                bool(s.vikey_api_base and s.vikey_api_key),
                "Kunci AI terisi.",
                "Kunci AI kosong: isi di Pengaturan (dibutuhkan mode Sendiri dan Leader).",
                wajib=False,
            ),
            _flag(
                "hub_token",
                bool(s.hub_token),
                "Token hub terisi.",
                "Token hub kosong: isi di Pengaturan (dibutuhkan mode Leader dan Follower).",
                wajib=False,
            ),
        ]

    def _binance_checks(self) -> list[Check]:
        s = self._settings
        if not self._apps.is_running(s.app_bundle_id):
            return [
                Check("binance", False, "Binance belum dibuka. Buka dan login dulu."),
                Check("window", False, "Ukuran jendela dicek setelah Binance dibuka."),
            ]
        running = Check("binance", True, "Binance berjalan.")
        try:
            rect = self._window.bounds(s.app_name)
        except BotError as exc:
            return [running, Check("window", False, f"Jendela Binance tidak terbaca: {exc}")]
        problem = window_size_problem(rect.width, rect.height)
        if problem:
            return [running, Check("window", False, problem)]
        return [
            running,
            Check("window", True, f"Ukuran jendela {rect.width}x{rect.height} sesuai."),
        ]

    def _api_check(self) -> Check:
        try:
            self._market.quote("BTCUSDT")
        except BotError as exc:
            return Check("api", False, f"API publik Binance tidak bisa dijangkau: {exc}")
        return Check("api", True, "API publik Binance bisa dijangkau.")


def _flag(id_: str, ok: bool, ok_text: str, fail_text: str, *, wajib: bool = True) -> Check:
    return Check(id_, ok, ok_text if ok else fail_text, wajib)
