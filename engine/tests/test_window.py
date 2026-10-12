from collections.abc import Sequence
from pathlib import Path

import pytest

from binance_bot.exceptions import CommandError, WindowError
from binance_bot.macos import MacWindowController, Rect, wait_for_window


class FlakyWindow:
    """Jendela yang baru muncul setelah beberapa kali dicoba."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def bounds(self, app_name: str) -> Rect:
        self.calls += 1
        if self.calls <= self.failures:
            raise WindowError("window 1 belum ada")
        return Rect(0, 33, 1470, 859)

    def click(self, x: int, y: int) -> None: ...

    def capture(self, rect: Rect, path: Path) -> None: ...


def test_wait_for_window_retries_until_window_appears() -> None:
    window = FlakyWindow(failures=3)
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    rect = wait_for_window(
        window, "Binance", timeout_s=10, interval_s=0.5, sleep=sleep, clock=lambda: now[0]
    )
    assert rect == Rect(0, 33, 1470, 859)
    assert window.calls == 4


def test_wait_for_window_reraises_after_timeout() -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(WindowError, match="belum ada"):
        wait_for_window(
            FlakyWindow(failures=999),
            "Binance",
            timeout_s=2,
            interval_s=0.5,
            sleep=sleep,
            clock=lambda: now[0],
        )


def test_rect_point_at_is_relative_to_window_origin() -> None:
    assert Rect(0, 33, 1470, 859).point_at(0.5, 0.0) == (735, 33)
    assert Rect(100, 50, 200, 100).point_at(1.0, 1.0) == (300, 150)


def test_rect_sub_cuts_relative_area_inside_window() -> None:
    assert Rect(0, 33, 1000, 800).sub(0.1, 0.25, 0.6, 0.75) == Rect(100, 233, 500, 400)


def test_bounds_parses_osascript_output() -> None:
    controller = MacWindowController(lambda args: "0, 33, 1470, 859\n")
    assert controller.bounds("Binance") == Rect(0, 33, 1470, 859)


def test_bounds_rejects_unexpected_output() -> None:
    with pytest.raises(WindowError):
        MacWindowController(lambda args: "bukan angka").bounds("Binance")


def test_click_delegates_to_mouse_with_screen_coordinates() -> None:
    clicks: list[tuple[int, int]] = []
    MacWindowController(mouse_click=lambda x, y: clicks.append((x, y))).click(1016, 166)
    assert clicks == [(1016, 166)]


def test_scroll_up_delegates_to_mouse_with_screen_coordinates() -> None:
    scrolls: list[tuple[int, int]] = []
    MacWindowController(mouse_scroll_up=lambda x, y: scrolls.append((x, y))).scroll_up(478, 786)
    assert scrolls == [(478, 786)]


def test_permission_failure_becomes_window_error_with_hint() -> None:
    def runner(args: Sequence[str]) -> str:
        raise CommandError("osascript tidak diizinkan akses bantuan")

    with pytest.raises(WindowError, match="Accessibility"):
        MacWindowController(runner).bounds("Binance")


def test_capture_uses_region_and_fails_when_no_file_written(tmp_path: Path) -> None:
    calls: list[Sequence[str]] = []

    def runner(args: Sequence[str]) -> str:
        calls.append(args)
        return ""

    target = tmp_path / "x.png"
    with pytest.raises(WindowError, match="Screen"):
        MacWindowController(runner).capture(Rect(0, 33, 1470, 859), target)
    assert list(calls[0]) == ["screencapture", "-x", "-R", "0,33,1470,859", str(target)]
