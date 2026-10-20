import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from binance_bot.filelock import ScreenTurn


def test_screen_turn_is_reentrant_within_one_bot(tmp_path: Path) -> None:
    turn = ScreenTurn(tmp_path / "screen.lock")
    with turn.hold(), turn.hold():  # jual otomatis di dalam giliran koin: tidak macet
        pass


def test_a_turn_held_by_another_bot_in_between_is_noticed(tmp_path: Path) -> None:
    path = tmp_path / "screen.lock"
    mine, other = ScreenTurn(path), ScreenTurn(path)
    with mine.hold():
        pass
    with mine.hold():
        assert not mine.changed_hands  # layar masih seperti yang ditinggalkan bot ini
    with other.hold():
        pass
    with mine.hold():
        assert mine.changed_hands  # halaman harus dibuka ulang, bukan diingat


@pytest.mark.skipif(sys.platform == "win32", reason="pemegang kunci memakai fcntl")
def test_the_second_bot_waits_for_its_turn_instead_of_failing(tmp_path: Path) -> None:
    path = tmp_path / "screen.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time\n"
            "f = open(sys.argv[1], 'a+b'); fcntl.flock(f, fcntl.LOCK_EX)\n"
            "print('held', flush=True); time.sleep(1.0)",
            str(path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
    started = time.monotonic()
    with ScreenTurn(path, timeout_s=10).hold():
        waited = time.monotonic() - started
    holder.wait()
    assert waited >= 0.5


def test_without_a_lock_file_there_is_no_waiting(tmp_path: Path) -> None:
    turn = ScreenTurn(None)
    with turn.hold():
        assert not turn.changed_hands


def test_a_bot_gives_way_to_another_bot_that_is_waiting(tmp_path: Path) -> None:
    path = tmp_path / "screen.lock"
    pauses: list[float] = []
    turn = ScreenTurn(path, sleep=pauses.append)
    with turn.hold():
        pass
    assert pauses == []  # tidak ada yang menunggu: langsung
    (tmp_path / "screen.lock.waiting").write_text("999999")  # bot lain baru saja menunggu
    with turn.hold():
        pass
    assert pauses == [ScreenTurn._GIVE_WAY_S]
    (tmp_path / "screen.lock.waiting").write_text(str(os.getpid()))  # tanda milik bot ini sendiri
    with turn.hold():
        pass
    assert len(pauses) == 1
