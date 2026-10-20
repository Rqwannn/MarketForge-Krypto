from typing import Any

import pytest

from binance_bot.exceptions import MarketDataError
from binance_bot.market import FuturesMarket, is_futures_symbol

RESPONSES: dict[str, Any] = {
    "exchangeInfo": {
        "symbols": [
            {
                "symbol": "STRKUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    },
    "ticker/bookTicker": {"bidPrice": "0.10831", "askPrice": "0.10833"},
    "ticker/24hr": {"priceChangePercent": "54.26"},
    "klines": [[0, "1", "2", "0.5", "1.5", "100", 899999]],
}


def fake_get(urls: list[str]) -> Any:
    def get(url: str) -> Any:
        urls.append(url)
        path = url.split("/fapi/v1/")[1].split("?")[0]
        return RESPONSES[path]

    return get


def test_rules_quote_and_klines_are_parsed() -> None:
    urls: list[str] = []
    market = FuturesMarket(get_json=fake_get(urls))

    assert market.rules("STRKUSDT").step == 0.1
    quote = market.quote("STRKUSDT")
    assert quote.change_pct == 54.26
    assert not any("premiumIndex" in u for u in urls)  # funding rate tidak diambil lagi
    assert quote.spread_pct == pytest.approx(0.0185, abs=0.0005)
    assert market.klines("STRKUSDT", "15m", limit=40)[0].high == 2.0
    assert any("interval=15m" in u and "limit=40" in u for u in urls)


def test_symbol_without_perpetual_is_rejected() -> None:
    with pytest.raises(MarketDataError, match="perpetual"):
        FuturesMarket(get_json=fake_get([])).rules("ABCUSDT")


@pytest.mark.parametrize("bad", ["../STRKUSDT", "STRK/USDT", "strkusdt", "STRKUSDT&x=1"])
def test_ocr_symbols_are_validated_before_any_request(bad: str) -> None:
    urls: list[str] = []
    assert not is_futures_symbol(bad)
    with pytest.raises(MarketDataError, match="tidak valid"):
        FuturesMarket(get_json=fake_get(urls)).quote(bad)
    assert urls == []


def test_single_letter_coin_is_a_valid_pair() -> None:
    assert is_futures_symbol("SUSDT")
    assert not is_futures_symbol("USDT")
