import sys
from pathlib import Path

import pytest

from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.system import build_system

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="lapisan Windows")


def test_candidate_paths_prefers_explicit_app_path() -> None:
    from binance_bot.windows.app_controller import candidate_paths

    env = {"BOT_APP_PATH": r"D:\Apps\Binance.exe", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    paths = candidate_paths("Binance.exe", env)
    assert paths[0] == Path(r"D:\Apps\Binance.exe")
    assert Path(r"C:\Users\x\AppData\Local\Programs\Binance\Binance.exe") in paths


def test_segment_line_splits_wide_column_gaps() -> None:
    from binance_bot.windows.ocr import _segment_line

    words = [
        ("STRKUSDT", 10.0, 5.0, 80.0, 12.0),
        ("Perp", 95.0, 5.0, 30.0, 12.0),
        ("+45,2%", 400.0, 5.0, 50.0, 12.0),
    ]
    segments = _segment_line(words)
    assert [[w[0] for w in seg] for seg in segments] == [["STRKUSDT", "Perp"], ["+45,2%"]]


def test_window_controller_refuses_non_numbers() -> None:
    from binance_bot.windows import WinWindowController

    with pytest.raises(ValueError):
        WinWindowController("Binance.exe").type_number("1\n")


def test_build_system_rejects_unknown_platform() -> None:
    with pytest.raises(BotError):
        build_system(Settings.from_env({}), platform="linux")


def test_group_rows_merges_ocr_lines_on_the_same_visual_row() -> None:
    from binance_bot.windows.ocr import _group_rows, _segment_line

    # "BTCUSDT" dan "Perpetual" datang sebagai dua line OCR terpisah di baris yang sama
    words = [
        ("BTCUSDT", 295.0, 528.0, 90.0, 20.0),
        ("83,923.60", 810.0, 517.0, 90.0, 20.0),
        ("Perpetual", 395.0, 530.0, 75.0, 18.0),
        ("$83,923.60", 823.0, 541.0, 78.0, 18.0),
    ]
    rows = _group_rows(words)
    texts = [[" ".join(w[0] for w in seg) for seg in _segment_line(row)] for row in rows]
    assert ["BTCUSDT Perpetual"] in texts
    assert any("83,923.60" in group for group in texts)
