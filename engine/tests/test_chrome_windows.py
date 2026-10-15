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
        self.images: dict[int, str] = {}
        self.titles: dict[int, str] = {}
        self.typed = ""  # isi kotak alamat
        self.drop_first = 0  # berapa kali ketikan kehilangan karakter pertamanya

    def find_windows(self, exe: str) -> list[int]:
        return list(self.windows)

    def force_to_front(self, hwnd: int) -> None:
        if self.focusable:
            self.front = hwnd

    def foreground_window(self) -> int:
        return self.front

    def browser_type_address(self, url: str, guard: object = None) -> None:
        assert callable(guard)
        for i in range(10):
            if self.steal_after is not None and i >= self.steal_after:
                self.front = 999
            if not guard():
                raise OSError("fokus berpindah")
        self.typed = url[1:] if self.drop_first else url  # karakter pertama hilang
        if self.drop_first:
            self.drop_first -= 1
        self.sent.append(("type", url))

    def browser_commit_address(self, guard: object = None) -> None:
        assert callable(guard)
        if not guard():
            raise OSError("fokus berpindah")
        self.sent.append(("commit", self.typed))

    def browser_zoom(self, steps: int, guard: object = None) -> None:
        assert callable(guard)
        if not guard():
            raise OSError("fokus berpindah")
        self.sent.append(("zoom", steps))

    def window_exists(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def process_image_name(self, hwnd: int) -> str | None:
        return self.images.get(hwnd, "chrome.exe")

    def window_title(self, hwnd: int) -> str:
        return self.titles.get(hwnd, "Tebbit - Trading Platform - Google Chrome")

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
    kwargs.setdefault("read_address", lambda hwnd: win.typed)
    return cw.WinChromeController(win=win, sleep=ticker.sleep, clock=ticker, **kwargs)  # type: ignore[arg-type]


def test_keys_go_to_chrome_only_after_it_is_in_front() -> None:
    win = FakeWin()
    make(win).open_url(TEBBIT, HOME_URL)
    assert win.sent == [("type", HOME_URL), ("commit", HOME_URL)]
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


def test_a_dropped_first_character_is_retyped_and_enter_waits_for_a_match() -> None:
    win = FakeWin()
    win.drop_first = 1  # percobaan pertama menjadi "ttps://..."
    make(win).open_url(TEBBIT, HOME_URL)
    assert win.sent == [("type", HOME_URL), ("type", HOME_URL), ("commit", HOME_URL)]


def test_enter_is_never_pressed_for_an_address_that_keeps_coming_out_wrong() -> None:
    win = FakeWin()
    win.drop_first = 99
    with pytest.raises(WindowError, match="Enter tidak ditekan"):
        make(win).open_url(TEBBIT, HOME_URL)
    assert not any(kind == "commit" for kind, _ in win.sent)


def test_autocomplete_suffix_is_accepted_because_it_is_deleted_before_enter() -> None:
    win = FakeWin()
    chrome = make(
        win, read_address=lambda hwnd: "tebbit.io/futures/contract/u_based/btw_usdt/extra"
    )
    chrome.open_url(TEBBIT, "https://tebbit.io/futures/contract/u_based/btw_usdt")
    assert [kind for kind, _ in win.sent] == ["type", "commit"]


def test_address_key_ignores_scheme_www_case_and_trailing_slash() -> None:
    assert cw.address_key("https://www.Tebbit.io/") == cw.address_key("tebbit.io") == "tebbit.io"
    assert cw.address_key("ttps://tebbit.io/") != cw.address_key("https://tebbit.io/")


def state_chrome(win: FakeWin, state: Path, **kwargs: object) -> cw.WinChromeController:
    return make(win, state_file=state, **kwargs)


def test_open_window_records_the_window_and_close_forgets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cw, "chrome_path", lambda: Path("chrome.exe"))
    state = tmp_path / "logs" / "tebbit_window.id"
    win = FakeWin()
    chrome = state_chrome(win, state, launch=lambda cmd: win.windows.append(TEBBIT))
    assert chrome.open_window() == TEBBIT
    assert state.read_text() == str(TEBBIT)
    chrome.close_window(TEBBIT)
    assert not state.exists() and TEBBIT not in win.windows


def test_a_leftover_tebbit_window_from_a_killed_run_is_closed_before_opening_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cw, "chrome_path", lambda: Path("chrome.exe"))
    state = tmp_path / "id"
    state.write_text("222")
    win = FakeWin()
    win.windows.append(222)
    chrome = state_chrome(win, state, launch=lambda cmd: win.windows.append(TEBBIT))
    chrome.open_window()
    assert 222 not in win.windows  # sisa putaran lalu ditutup
    assert 999 in win.windows  # jendela lain milik pengguna tidak disentuh
    assert state.read_text() == str(TEBBIT)


@pytest.mark.parametrize(
    ("image", "title"),
    [("notepad.exe", "Tebbit - catatan"), ("chrome.exe", "Crypto Discussion - Claude")],
)
def test_a_reused_window_id_that_is_not_our_tebbit_window_is_left_alone(
    image: str, title: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cw, "chrome_path", lambda: Path("chrome.exe"))
    state = tmp_path / "id"
    state.write_text("222")
    win = FakeWin()
    win.windows.append(222)
    win.images[222], win.titles[222] = image, title
    state_chrome(win, state, launch=lambda cmd: win.windows.append(TEBBIT)).open_window()
    assert 222 in win.windows
