from collections.abc import Iterator

import pytest

from binance_bot.analysis import AnalysisRecord
from binance_bot.exceptions import AnalysisError, ConfigError, HubError
from binance_bot.hub import AnalysisStore, HubClient, HubServer
from fakes import record

TOKEN = "rahasia-bersama"


@pytest.fixture
def hub() -> Iterator[tuple[AnalysisStore, str]]:
    """Server hub sungguhan di localhost, port acak, jam hub tetap di 1600."""
    store = AnalysisStore()
    server = HubServer(store, TOKEN, host="127.0.0.1", port=0, clock=lambda: 1600.0)
    server.start()
    try:
        yield store, f"http://127.0.0.1:{server.port}"
    finally:
        server.stop()


def test_follower_reads_all_and_single_results_with_hub_clock_age(
    hub: tuple[AnalysisStore, str],
) -> None:
    store, url = hub
    store.put(record("CFXUSDT", rank=2, analyzed_at=1000.0))
    store.put(record("STRKUSDT", rank=1, analyzed_at=1300.0))
    client = HubClient(url, TOKEN)

    assert [s.record.symbol for s in client.list()] == ["STRKUSDT", "CFXUSDT"]
    shared = client.get("CFXUSDT")
    assert shared is not None
    assert shared.record == record("CFXUSDT", rank=2, analyzed_at=1000.0)
    assert shared.age_s == 600.0


def test_unknown_symbol_is_none(hub: tuple[AnalysisStore, str]) -> None:
    _, url = hub
    assert HubClient(url, TOKEN).get("ZKUSDT") is None


def test_wrong_token_is_rejected(hub: tuple[AnalysisStore, str]) -> None:
    store, url = hub
    store.put(record())
    with pytest.raises(HubError, match="token"):
        HubClient(url, "tebakan").list()


def test_unreachable_hub_is_a_hub_error() -> None:
    server = HubServer(AnalysisStore(), TOKEN, host="127.0.0.1", port=0)
    server.start()
    port = server.port
    server.stop()
    with pytest.raises(HubError, match="tidak bisa dihubungi"):
        HubClient(f"http://127.0.0.1:{port}", TOKEN, timeout_s=2).list()


def test_hub_and_client_require_token_and_address() -> None:
    with pytest.raises(ConfigError):
        HubServer(AnalysisStore(), "")
    with pytest.raises(ConfigError):
        HubClient("http://x:1", "")
    with pytest.raises(ConfigError):
        HubClient("", TOKEN)


def test_store_fresh_respects_ttl() -> None:
    store = AnalysisStore()
    store.put(record("STRKUSDT", analyzed_at=1000.0))
    assert store.fresh("STRKUSDT", max_age_s=900, now=1900.0) is not None
    assert store.fresh("STRKUSDT", max_age_s=900, now=1901.0) is None
    assert store.fresh("CFXUSDT", max_age_s=900, now=1000.0) is None


def test_record_round_trips_through_dict() -> None:
    original = record("MBLUSDT", rank=3, analyzed_at=1234.5)
    assert AnalysisRecord.from_dict(original.to_dict()) == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(symbol="../../etc"),
        lambda d: d.update(symbol="STRK/USDT"),
        lambda d: d.update(rank="1"),
        lambda d: d.update(rank=True),
        lambda d: d.update(analyzed_at="kemarin"),
        lambda d: d.update(ma7_below_ma25_count="tiga"),
        lambda d: d.update(ma7_below_ma25_now="ya"),
        lambda d: d.update(summary=""),
        lambda d: d.pop("ma7_below_ma25_count"),
    ],
)
def test_record_from_untrusted_data_is_validated(mutate: object) -> None:
    data = record().to_dict()
    mutate(data)  # type: ignore[operator]
    with pytest.raises(AnalysisError):
        AnalysisRecord.from_dict(data)
