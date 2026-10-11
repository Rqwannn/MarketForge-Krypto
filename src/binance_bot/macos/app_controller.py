"""Kontrol aplikasi macOS lewat `open` dan `lsappinfo` (keduanya bawaan, tanpa izin tambahan)."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol

from binance_bot.exceptions import AppLaunchError, CommandError

logger = logging.getLogger(__name__)

Runner = Callable[[Sequence[str]], str]

_BUNDLE_ID_PATTERN = re.compile(r'"CFBundleIdentifier"\s*=\s*"([^"]+)"')


class AppController(Protocol):
    """Kontrak yang dipakai task. Memudahkan pengujian dengan fake."""

    def is_running(self, bundle_id: str) -> bool: ...

    def launch(self, bundle_id: str) -> None: ...

    def frontmost_bundle_id(self) -> str | None: ...


def run_command(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandError(f"Gagal menjalankan {args[0]}: {exc}") from exc
    if result.returncode != 0:
        raise CommandError(f"{' '.join(args)} gagal ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


class MacAppController:
    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner

    def is_running(self, bundle_id: str) -> bool:
        return bool(self._run(["lsappinfo", "find", f"bundleid={bundle_id}"]).strip())

    def launch(self, bundle_id: str) -> None:
        """Buka aplikasi, atau bawa ke depan jika sudah berjalan."""
        logger.info("Membuka aplikasi %s", bundle_id)
        try:
            self._run(["open", "-b", bundle_id])
        except CommandError as exc:
            raise AppLaunchError(f"Tidak bisa membuka {bundle_id}: {exc}") from exc

    def frontmost_bundle_id(self) -> str | None:
        asn = self._run(["lsappinfo", "front"]).strip()
        if not asn:
            return None
        info = self._run(["lsappinfo", "info", "-only", "bundleid", asn])
        match = _BUNDLE_ID_PATTERN.search(info)
        return match.group(1) if match else None
