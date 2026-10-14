"""Pengendali Chrome Tebbit di Windows: tombol hanya dikirim bila jendela Tebbit yang aktif."""

import sys
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("khusus Windows", allow_module_level=True)

from binance_bot.exceptions import WindowError
from binance_bot.tebbit_web import chrome_windows as cw
from binance_bot.tebbit_web.chrome import HOME_URL

TEBBIT = 111


class FakeWin:
    """Pengganti `win32`: mencatat apa yang dikirim, dan fokus bisa diatur."""

    def __init__(self, focusable: bool = True) -> None:
        self.focusable = focusable
        self.front = 999  # jendela lain (mis. WhatsApp) yang sedang aktif
        self.windows: list[int] = [999]
        self.sent: list[tuple[str, object]] = []
        self.steal_after: int | None = None  # setelah N pemeriksaan fokus, aplikasi lain merebut

    def find_windows(self, exe: str) -> list[int]:
        return list(self.windows)

    def force_to_front(self, hwnd: int) -> None:
        if self.focusable:
            self.front = hwnd

    def foreground_window(self) -> int:
        return self.front

    def browser_go(self, url: str, guard: object = None) -> None:
        assert callable(guard)
        for i in range(10):
            if self.steal_after is not None and i >= self.steal_after:
                self.front = 999
            if not guard():
                raise OSError("fokus berpindah")
        self.sent.append(("go", url))

    def browser_zoom(self, steps: int, guard: object = None) -> None:
        assert callable(guard)
        if not guard():
            raise OSError("fokus berpindah")
        self.sent.append(("zoom", steps))

    def window_exists(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def close_window(self, hwnd: int) -> None:
        self.windows.remove(hwnd)


class Ticker:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make(win: FakeWin, **kwargs: object) -> cw.WinChromeController:
    ticker = Ticker()
    return cw.WinChromeController(win=win, sleep=ticker.sleep, clock=ticker, **kwargs)  # type: ignore[arg-type]


def test_keys_go_to_chrome_only_after_it_is_in_front() -> None:
    win = FakeWin()
    make(win).open_url(TEBBIT, HOME_URL)
    assert win.sent == [("go", HOME_URL)]
    assert win.front == TEBBIT


def test_nothing_is_typed_when_windows_refuses_to_bring_chrome_to_front() -> None:
    win = FakeWin(focusable=False)
    with pytest.raises(WindowError, match="tidak bisa dibawa ke depan"):
        make(win).open_url(TEBBIT, HOME_URL)
    assert win.sent == []


def test_typing_stops_when_another_app_takes_focus_midway() -> None:
    win = FakeWin()
    win.steal_after = 3
    with pytest.raises(WindowError, match="Tombol tidak dikirim"):
        make(win).open_url(TEBBIT, HOME_URL)
    assert win.sent == []


def test_zoom_needs_the_window_and_the_focus() -> None:
    win = FakeWin()
    with pytest.raises(WindowError, match="belum dibuka"):
        make(win).set_zoom(2)
    make(win).set_zoom(2, TEBBIT)
    assert win.sent == [("zoom", 2)]
    blocked = FakeWin(focusable=False)
    with pytest.raises(WindowError):
        make(blocked).set_zoom(2, TEBBIT)
    assert blocked.sent == []


def test_only_tebbit_addresses_can_be_typed() -> None:
    win = FakeWin()
    with pytest.raises(WindowError, match="bukan halaman"):
        make(win).open_url(TEBBIT, "https://evil.example/")
    assert win.sent == []


def test_open_window_returns_the_new_window(monkeypatch: pytest.MonkeyPatch) -> None:
    win = FakeWin()
    monkeypatch.setattr(cw, "chrome_path", lambda: Path("chrome.exe"))
    launched: list[list[str]] = []

    def launch(cmd: list[str]) -> None:
        launched.append(cmd)
        win.windows.append(TEBBIT)

    assert make(win, launch=launch).open_window() == TEBBIT
    assert launched == [["chrome.exe", "--new-window", HOME_URL]]


def test_open_window_gives_up_when_no_window_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cw, "chrome_path", lambda: Path("chrome.exe"))
    with pytest.raises(WindowError, match="tidak muncul"):
        make(FakeWin(), launch=lambda cmd: None).open_window()


def test_current_url_gets_a_scheme_and_retries() -> None:
    answers = iter(["", "", "tebbit.io/futures/contract/u_based/truth_usdt"])
    chrome = make(FakeWin(), read_address=lambda hwnd: next(answers))
    assert chrome.current_url(TEBBIT) == "https://tebbit.io/futures/contract/u_based/truth_usdt"


def test_current_url_fails_when_the_address_never_shows() -> None:
    with pytest.raises(WindowError, match="tidak terbaca"):
        make(FakeWin(), read_address=lambda hwnd: "").current_url(TEBBIT)


def test_chrome_is_found_in_the_usual_places(tmp_path: Path) -> None:
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert cw.chrome_path({"ProgramFiles": str(tmp_path)}) == exe
    assert cw.chrome_path({"BOT_CHROME_PATH": str(exe)}) == exe
    with pytest.raises(WindowError, match="Chrome tidak ditemukan"):
        cw.chrome_path({})
