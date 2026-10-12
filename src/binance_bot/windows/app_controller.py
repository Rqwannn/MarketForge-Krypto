"""Kontrol aplikasi Windows: cek berjalan, luncurkan/bawa ke depan, aplikasi aktif.

Di Windows "bundle id" berarti nama file exe, mis. "Binance.exe".
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from binance_bot.exceptions import AppLaunchError
from binance_bot.macos.app_controller import run_command
from binance_bot.windows import win32

logger = logging.getLogger(__name__)

Runner = Callable[[Sequence[str]], str]


def candidate_paths(exe_name: str, env: Mapping[str, str] | None = None) -> list[Path]:
    """Lokasi pemasangan umum, plus `BOT_APP_PATH` bila diisi."""
    env = os.environ if env is None else env
    paths: list[Path] = []
    if env.get("BOT_APP_PATH"):
        paths.append(Path(env["BOT_APP_PATH"]))
    stem = exe_name.removesuffix(".exe")
    for root_key in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = env.get(root_key)
        if not root:
            continue
        base = Path(root)
        paths += [
            base / "Programs" / stem / exe_name,
            base / stem / exe_name,
            base / stem / "app" / exe_name,
        ]
    return paths


class WinAppController:
    def __init__(self, runner: Runner = run_command, env: Mapping[str, str] | None = None) -> None:
        self._run = runner
        self._env = env

    def is_running(self, bundle_id: str) -> bool:
        if win32.find_windows(bundle_id):
            return True
        out = self._run(["tasklist", "/FI", f"IMAGENAME eq {bundle_id}", "/FO", "CSV", "/NH"])
        return bundle_id.casefold() in out.casefold()

    def launch(self, bundle_id: str) -> None:
        """Bawa ke depan bila sudah berjalan; kalau belum, jalankan dari lokasi pemasangan."""
        windows = win32.find_windows(bundle_id)
        if windows:
            logger.info("Membawa %s ke depan", bundle_id)
            win32.bring_to_front(windows[0])
            return
        for path in candidate_paths(bundle_id, self._env):
            if path.is_file():
                logger.info("Membuka aplikasi %s", path)
                try:
                    os.startfile(path)  # type: ignore[attr-defined,unused-ignore]
                except OSError as exc:
                    raise AppLaunchError(f"Tidak bisa membuka {path}: {exc}") from exc
                return
        raise AppLaunchError(
            f"{bundle_id} tidak ditemukan. Isi BOT_APP_PATH di .env dengan path lengkap "
            "Binance.exe (klik kanan pintasan Binance > Open file location)."
        )

    def frontmost_bundle_id(self) -> str | None:
        return win32.foreground_image_name()
