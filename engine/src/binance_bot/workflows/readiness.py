from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from binance_bot.binance_desktop.layout import (
    EXPECTED_WINDOW,
    screen_too_small,
    window_ready,
    window_target,
)
from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.macos import AppController, Rect, WindowController
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
        screens: Callable[[], Sequence[Rect]],
        output: Callable[[str], None] = print,
    ) -> None:
        self._settings = settings
        self._apps = apps
        self._window = window
        self._market = market
        self._accessibility = accessibility
        self._screen_capture = screen_capture
        self._screens = screens
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
        areas = self._screens()
        auto = "Jendela Binance ditampilkan dan diatur otomatis saat bot mulai."
        fits = any(a.width >= EXPECTED_WINDOW[0] and a.height >= EXPECTED_WINDOW[1] for a in areas)
        screen_check = Check("window", fits, auto if fits else screen_too_small(areas))
        if not self._apps.is_running(s.app_bundle_id):
            return [
                Check("binance", False, "Binance belum dibuka. Buka dan login dulu."),
                screen_check,
            ]
        running = Check("binance", True, "Binance berjalan.")
        try:
            rect = self._window.bounds(s.app_name)
        except BotError:
            # Jendela di Desktop (Space) lain atau diperkecil tidak terbaca dari sini; bot
            # membawa Binance ke depan saat mulai, jadi yang perlu dicek hanya ukuran layar.
            return [running, screen_check]
        if window_ready(rect, areas):
            return [
                running,
                Check("window", True, f"Ukuran jendela {rect.width}x{rect.height} sesuai."),
            ]
        if window_target(rect, areas) is None:
            return [running, Check("window", False, screen_too_small(areas))]
        return [running, Check("window", True, auto)]

    def _api_check(self) -> Check:
        try:
            self._market.quote("BTCUSDT")
        except BotError as exc:
            return Check("api", False, f"API publik Binance tidak bisa dijangkau: {exc}")
        return Check("api", True, "API publik Binance bisa dijangkau.")


def _flag(id_: str, ok: bool, ok_text: str, fail_text: str, *, wajib: bool = True) -> Check:
    return Check(id_, ok, ok_text if ok else fail_text, wajib)
