"""Teks layar Tebbit (OCR, bahasa Inggris) -> data: daftar gainers, harga, order book, margin."""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.exceptions import ScreenReadError
from binance_bot.macos import TextLine
from binance_bot.tebbit_web import layout_tebbit as lay

# OCR Windows kadang membaca "%" sebagai "0/0" pada font kecil.
_PERCENT = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*(?:%|0/0)$")
_PAIR = re.compile(r"([A-Z0-9]{1,20}USDT)\b")
_PRICE = re.compile(r"^\d[\d,]*\.\d{2,}$")
_LEVERAGE = re.compile(r"(\d{1,3})\s*[xX]\b")
_URL_PAIR = re.compile(r"^/futures/contract/u_based/([^/?#]+)$")


def symbol_from_url(url: str) -> str:
    """https://tebbit.io/futures/contract/u_based/truth_usdt -> TRUTHUSDT."""
    match = _URL_PAIR.match(urlsplit(url).path)
    if not match:
        raise ScreenReadError(f"Alamat bukan halaman koin Futures Tebbit: {url!r}")
    return unquote(match.group(1)).upper().replace("_", "")


def contract_url(symbol: str) -> str:
    """TRUTHUSDT -> https://tebbit.io/futures/contract/u_based/truth_usdt (URL langsung koin)."""
    if not re.fullmatch(r"[A-Z0-9]{1,20}USDT", symbol):
        raise ScreenReadError(f"Nama koin tidak dikenal untuk Tebbit: {symbol!r}")
    return f"https://tebbit.io/futures/contract/u_based/{symbol[:-4].lower()}_usdt"


def parse_gainer_rows(
    lines: Sequence[TextLine], area: tuple[float, float, float, float]
) -> list[tuple[GainerRow, tuple[float, float]]]:
    """Baris daftar Futures: (GainerRow, titik klik relatif jendela), urut dari atas.

    `lines` relatif terhadap gambar `area`. Baris dikenali dari persentase di kolom "Change";
    nama pair dicari di kolom nama pada ketinggian yang sama (nama beraksara non-Latin bisa
    gagal terbaca, lalu diberi nama sementara; nama asli dibaca dari alamat halaman koin).
    """
    x0, y0, x1, y1 = area

    def to_x(fx: float) -> float:
        return x0 + fx * (x1 - x0)

    def to_y(fy: float) -> float:
        return y0 + fy * (y1 - y0)

    percents = []
    for line in lines:
        match = _PERCENT.match(line.text.strip())
        x = to_x(line.x)
        if match and lay.FUTURES_PERCENT_X[0] <= x <= lay.FUTURES_PERCENT_X[1]:
            percents.append((to_y(line.y), x, float(match.group(1).replace(",", "."))))
    percents.sort()
    found = []
    for y, percent_x, change in percents[: lay.MAX_ROWS]:
        names = [
            line
            for line in lines
            if lay.FUTURES_NAME_X[0] <= to_x(line.x) <= lay.FUTURES_NAME_X[1]
            and abs(to_y(line.y) - y) < 0.035
            and "Perpetual" not in line.text
        ]
        names.sort(key=lambda line: abs(to_y(line.y) - y))
        found.append((y, percent_x, change, names))
    # Baris yang namanya tidak terbaca diklik di kolom nama baris lain (kolomnya sejajar);
    # tanpa nama sama sekali, di persentasenya. Keduanya di dalam baris, bukan margin kosong.
    name_x = next((to_x(names[0].x) for *_, names in found if names), None)
    rows = []
    for index, (y, percent_x, change, names) in enumerate(found, start=1):
        pair = next((m.group(1) for line in names if (m := _PAIR.search(line.text))), None)
        x = to_x(names[0].x) if names else (name_x if name_x is not None else percent_x)
        rows.append((GainerRow(index, pair or f"#{index}", change), (x, y)))
    return rows


def parse_header(texts: Sequence[str]) -> tuple[float, float]:
    """Header koin -> (harga terakhir, perubahan 24 jam %)."""
    joined = " ".join(texts).replace("_", ".")  # OCR kadang membaca titik desimal sebagai "_"
    # Harga terakhir tepat diikuti perubahannya, mis. "0.15384 +11.35%" (OCR bisa menyisipkan
    # spasi setelah tanda: "+ 11.35%").
    # Harga header tidak dipakai SOP (bid/ask dari order book); titik desimalnya kadang hilang.
    found = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([+-])\s*(\d+(?:\.\d+)?)\s*(?:%|0/0)", joined)
    if found:
        price, sign, change = found.groups()
        return float(price.replace(",", "")), float(sign + change)
    # Angka harga kadang tidak terbaca sama sekali; yang dibutuhkan SOP hanya persen perubahannya.
    only = re.search(r"([+-])\s*(\d+(?:\.\d+)?)\s*(?:%|0/0)", joined)
    if not only:
        raise ScreenReadError(f"Perubahan 24 jam tidak terbaca di header: {texts}")
    return float("nan"), float(only.group(1) + only.group(2))


def parse_order_book(
    lines: Sequence[TextLine], area: tuple[float, float, float, float]
) -> tuple[float, float]:
    """Order book -> (bid terbaik, ask terbaik); penanda tengah = tulisan "Mark Price"."""
    _, y0, _, y1 = area
    mark_y = next(
        (y0 + line.y * (y1 - y0) for line in lines if "Mark" in line.text and "Price" in line.text),
        None,
    )
    if mark_y is None:
        raise ScreenReadError("Order book Tebbit tidak terbaca (tulisan 'Mark Price' tidak ada)")
    asks, bids = [], []
    for line in lines:
        text = line.text.strip().replace("_", ".")  # titik desimal sering terbaca "_"
        if line.x > 0.3 or not _PRICE.match(text):
            continue
        y = y0 + line.y * (y1 - y0)
        value = float(text.replace(",", ""))
        if y < mark_y - 0.03:
            asks.append(value)
        elif y > mark_y + 0.02:
            bids.append(value)
    if not asks or not bids:
        raise ScreenReadError(f"Order book kosong (ask {len(asks)}, bid {len(bids)})")
    return max(bids), min(asks)


def parse_margin(texts: Sequence[str]) -> MarginSettings:
    """Panel "Cross·Merge  75X" -> mode margin dan leverage."""
    joined = " ".join(texts)
    leverage = _LEVERAGE.search(joined)
    if not leverage:
        raise ScreenReadError(f"Leverage tidak terbaca di panel margin: {texts}")
    return MarginSettings(isolated="isolated" in joined.casefold(), leverage=int(leverage.group(1)))
