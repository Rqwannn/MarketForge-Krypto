import pytest

from binance_bot.config import Settings
from binance_bot.exceptions import AppTimeoutError
from binance_bot.workflows import OpenBinanceWorkflow as OpenBinanceTask

BUNDLE = "com.binance.BinanceDesktop"


class FakeController:
    def __init__(self, front_sequence: list[str | None], running: bool = False) -> None:
        self._front = iter(front_sequence)
        self._last: str | None = None
        self.running = running
        self.launched: list[str] = []

    def is_running(self, bundle_id: str) -> bool:
        return self.running

    def launch(self, bundle_id: str) -> None:
        self.launched.append(bundle_id)

    def frontmost_bundle_id(self) -> str | None:
        self._last = next(self._front, self._last)
        return self._last


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_task(controller: FakeController, timeout: float = 5.0) -> OpenBinanceTask:
    clock = FakeClock()
    settings = Settings(launch_timeout_s=timeout, poll_interval_s=1.0)
    return OpenBinanceTask(settings, controller, sleep=clock.sleep, clock=clock)


def test_launches_and_waits_until_frontmost() -> None:
    controller = FakeController(["com.google.Chrome", "com.google.Chrome", BUNDLE])
    make_task(controller).run()
    assert controller.launched == [BUNDLE]


def test_already_running_is_left_untouched() -> None:
    controller = FakeController(["com.google.Chrome"], running=True)
    make_task(controller).run()
    assert controller.launched == []


def test_raises_when_never_frontmost() -> None:
    controller = FakeController(["com.google.Chrome"])
    with pytest.raises(AppTimeoutError):
        make_task(controller, timeout=3.0).run()
