"""Kunci antar-proses: satu pemegang sekaligus (Mac dan Windows).

Dipakai agar beberapa bot (beberapa proses engine) di satu laptop tidak bentrok: penjualan dan
pemakaian layar bursa bergiliran, dan jurnal tidak ditulis dua proses sekaligus. Pemegang kedua
menunggu sampai kunci dilepas, lalu membaca keadaan terbaru.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO

from binance_bot.exceptions import BotError

logger = logging.getLogger(__name__)


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
def _held(
    path: Path,
    *,
    timeout_s: float,
    poll_s: float,
    busy: str,
    on_wait: Callable[[bool], None] | None = None,  # dipanggil tiap kali menunggu (True = pertama)
) -> Iterator[IO[bytes]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        deadline = time.monotonic() + timeout_s
        waited = False
        while True:
            try:
                _try_lock(handle)
                break
            except OSError:
                if on_wait is not None:
                    on_wait(not waited)
                waited = True
                if time.monotonic() >= deadline:
                    raise BotError(
                        f"{busy} lebih dari {timeout_s:.0f} detik; coba lagi nanti"
                    ) from None
                time.sleep(poll_s)
        try:
            yield handle
        finally:
            _unlock(handle)
    finally:
        handle.close()


@contextmanager
def exclusive(
    path: Path,
    *,
    timeout_s: float = 300.0,
    poll_s: float = 0.5,
    busy: str = "Bot lain masih menjual",
) -> Iterator[None]:
    """Tahan kunci `path` selama blok berjalan; tunggu bila proses lain memegangnya.

    Tidak re-entrant: proses yang sama tidak boleh mengambil kunci yang sama dua kali bertumpuk.
    """
    with _held(path, timeout_s=timeout_s, poll_s=poll_s, busy=busy):
        yield


class ScreenTurn:
    """Giliran memakai layar (mouse, keyboard, jendela bursa): satu bot pada satu waktu.

    Semua bot di laptop ini (Binance maupun Tebbit) berbagi satu mouse dan satu layar, jadi satu
    rangkaian aksi (buka koin, baca grafik, isi form, tekan tombol; atau tutup posisi) dijalankan
    utuh dalam satu giliran. Bot lain menunggu, tidak dibatalkan. Re-entrant di dalam satu proses.

    Bergantian: bot yang baru selesai satu giliran memberi kesempatan dulu bila ada bot lain yang
    sedang menunggu (mis. untuk jual otomatis), bukan langsung mengambil giliran berikutnya.

    `changed_hands` bernilai True setelah giliran sebelumnya dipegang proses lain: halaman di layar
    mungkin sudah diganti bot itu, jadi navigator tidak boleh memakai ingatan halamannya.
    """

    TIMEOUT_S = 900.0  # satu giliran bot lain paling lama sekitar 1-2 menit per koin
    _POLL_S = 0.5
    _WAITING_FRESH_S = 2.0  # tanda menunggu diperbarui tiap _POLL_S selama bot itu menunggu
    _GIVE_WAY_S = 1.5  # cukup untuk bot yang menunggu mengambil giliran

    def __init__(
        self,
        path: Path | None,
        *,
        timeout_s: float = TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._path = path
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._depth = 0
        self._token = ""  # penanda giliran terakhir milik proses ini
        self._seq = 0
        self.changed_hands = False

    def _queue(self) -> Path:
        assert self._path is not None
        return self._path.with_name(self._path.name + ".waiting")

    def _give_way(self) -> None:
        """Ada bot lain yang sedang menunggu giliran: biarkan ia lebih dulu."""
        try:
            queue = self._queue()
            other = queue.read_text(encoding="utf-8") != str(os.getpid())
            fresh = time.time() - queue.stat().st_mtime < self._WAITING_FRESH_S
        except OSError:
            return
        if other and fresh:
            self._sleep(self._GIVE_WAY_S)

    @contextmanager
    def hold(self) -> Iterator[None]:
        if self._path is None or self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return

        def waiting(first: bool) -> None:
            if first:
                logger.info("Menunggu giliran layar: bot lain sedang memakai bursa")
            with suppress(OSError):  # tanda menunggu: bot pemegang giliran memberi kesempatan
                self._queue().write_text(str(os.getpid()), encoding="utf-8")

        self._give_way()
        with _held(
            self._path,
            timeout_s=self._timeout_s,
            poll_s=self._POLL_S,
            busy="Bot lain masih memakai layar",
            on_wait=waiting,
        ) as handle:
            handle.seek(0)
            last = handle.read().decode("utf-8", "replace")
            self.changed_hands = last != self._token
            self._seq += 1
            self._token = f"{os.getpid()}:{self._seq}"
            handle.seek(0)
            handle.truncate()
            handle.write(self._token.encode())
            handle.flush()
            self._depth = 1
            try:
                yield
            finally:
                self._depth = 0
