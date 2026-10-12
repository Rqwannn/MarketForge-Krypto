from collections.abc import Sequence

from binance_bot.macos import MacAppController


def make_runner(outputs: dict[str, str]):
    calls: list[list[str]] = []

    def runner(args: Sequence[str]) -> str:
        calls.append(list(args))
        return outputs.get(args[1], "")

    return runner, calls


def test_is_running_true_when_lsappinfo_returns_asn() -> None:
    runner, _ = make_runner({"find": "ASN:0x0-0x1c1060ea:\n"})
    assert MacAppController(runner).is_running("x.y") is True


def test_is_running_false_when_output_empty() -> None:
    runner, _ = make_runner({"find": "\n"})
    assert MacAppController(runner).is_running("x.y") is False


def test_frontmost_bundle_id_parses_lsappinfo() -> None:
    runner, _ = make_runner(
        {
            "front": "ASN:0x0-0x1c1060ea:\n",
            "info": '"CFBundleIdentifier"="com.binance.BinanceDesktop"\n',
        }
    )
    assert MacAppController(runner).frontmost_bundle_id() == "com.binance.BinanceDesktop"


def test_launch_uses_open_with_bundle_id() -> None:
    runner, calls = make_runner({})
    MacAppController(runner).launch("com.binance.BinanceDesktop")
    assert calls == [["open", "-b", "com.binance.BinanceDesktop"]]
