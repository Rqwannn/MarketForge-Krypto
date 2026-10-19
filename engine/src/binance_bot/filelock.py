"""Kunci antar-proses: satu pemegang sekaligus (Mac dan Windows).

Dipakai agar dua bot (dua proses engine) tidak menjual bersamaan: penjualan memakai layar bursa,
jadi harus bergiliran. Pemegang kedua menunggu sampai kunci dilepas, lalu membaca keadaan terbaru.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from binance_bot.exceptions import BotError


def _try_lock(handle: IO[bytes]) -> None:
    """Ambil kunci tanpa menunggu; OSError bila sedang dipegang proses lain."""
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive(path: Path, *, timeout_s: float = 300.0, poll_s: float = 0.5) -> Iterator[None]:
    """Tahan kunci `path` selama blok berjalan; tunggu bila proses lain memegangnya."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                _try_lock(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise BotError(
                        f"Bot lain masih menjual lebih dari {timeout_s:.0f} detik; coba lagi nanti"
                    ) from None
                time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()
