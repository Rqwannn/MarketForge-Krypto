"""Parameter SOP "Top Gainers (Short dan Long)" (PDF V4, 23 Okt 2026).

Short, leverage 2x, margin 50% per posisi, chart 15 menit, pantau top 5, filter pola garis per
platform, jual di minimal 3% profit (dasar harga). Sejak V4 (23 Okt) juga LONG dengan target
minimal 4%, cutloss 10%, dan batas waktu 2,5-3 jam; ketiganya dipilih pengguna di aplikasi, dan
tanpa pilihan itu bot tetap short saja, tanpa stop-loss dan tanpa batas waktu (aturan V3). Angka
pola "minimal 2 kali di bawah" masih usulan. Batas jumlah posisi (maksimal 2) tidak dipakai atas
keputusan 15 Okt dan 23 Okt.
"""

from __future__ import annotations

from dataclasses import dataclass

from binance_bot.exceptions import ConfigError

SIGNAL_SOURCES = ("ai", "data")
SIDES = ("short", "long")
TOPS = range(1, 6)  # Top 1..5 gainers
# Batas waktu V4: sesudah 2,5 jam jual begitu untung bersih, di jam ke-3 jual apa pun kondisinya.
HOLD_GREEN_H = 2.5
HOLD_MAX_H = 3.0
REQUIRED_TEST_TRADES = 50  # fase uji di PDF
PASS_MARGIN = 0.05  # "selisih yang jelas" di atas titik impas: tafsiran 5 poin persen
# Contoh rugi V3 untuk titik impas sebelum ada rugi sungguhan: STRK, harga naik 21,8%.
REFERENCE_LOSS_PCT = 21.8


@dataclass(frozen=True, slots=True)
class SopParams:
    capital_usdt: float | None = None  # modal (USDT)
    # Modal dari saldo: modal = bagian ini x saldo USDT tersedia di form order, dibaca ulang setiap
    # akan masuk posisi (1,0 = Max, 0,5 = Setengah). None = modal tetap `capital_usdt`.
    capital_share: float | None = None
    order_usdt: float | None = None  # JUMLAH manual: ukuran order USDT (menimpa margin x leverage)
    margin_pct: float = 50.0  # beliau: margin 50% modal per posisi
    leverage: int = 2  # beliau: 2x (nilai posisi per koin = 100% modal)
    # Masuk ulang koin yang sama setelah terjual: paling banyak sekian kali per hari (20 Okt).
    max_reentries: int = 3
    target_pct: float = 3.0  # V3: jual saat untung 3-5%; dasar harga, mulai di 3% (usulan)
    # V4: arah per Top. short_tops None = short di semua Top yang dipantau (aturan lama). Mis.
    # short_tops=(2, 3, 4), long_tops=(1, 5): Top 2-4 hanya short, Top 1 dan 5 hanya long. Top yang
    # ada di keduanya boleh short atau long (grafik yang layak keduanya tidak dimasuki).
    short_tops: tuple[int, ...] | None = None
    long_tops: tuple[int, ...] = ()
    long_target_pct: float = 4.0  # V4: LONG dijual saat harga naik 4-5%; mulai di 4%
    stop_pct: float | None = None  # V4: cutloss saat harga melawan posisi sekian persen (10)
    time_limit: bool = False  # V4: batas waktu 2,5-3 jam (HOLD_GREEN_H, HOLD_MAX_H)
    min_crosses: int = 2  # usulan: MA7 minimal 2 kali di bawah MA25 = pola OK
    min_gain_pct: float = 0.0  # V2 tidak mensyaratkan kenaikan minimal; isi untuk menyaring
    review_after_h: float = 24.0  # V3: pantau posisi yang ditahan lebih dari satu hari
    fee_pct: float = 0.1  # riwayat: fee masuk + keluar per putaran
    # SOP V2 hanya menyebut "spread lebar", tanpa angka. Longgar dulu sampai Pak Saputra
    # menentukan batasnya: koin ETF (UVXY, SQQQ) spread-nya 0,1-0,25%.
    # Funding rate sengaja TIDAK menyaring koin (keputusan tim 20 Okt 2026): posisi scalping
    # singkat, jadi biaya funding per periode tidak relevan untuk memilih koin.
    max_spread_pct: float = 0.3
    signal_source: str = "ai"  # siapa yang membaca pola garis kuning: "ai" atau "data"

    def validate(self) -> None:
        errors = []
        if self.capital_usdt is None and self.order_usdt is None and self.capital_share is None:
            errors.append("isi MODAL (USDT, max, atau setengah) atau JUMLAH (USDT)")
        if self.capital_share is not None and not 0 < self.capital_share <= 1:
            errors.append("bagian saldo untuk modal harus di antara 0 dan 1")
        if self.capital_usdt is not None and self.capital_usdt <= 0:
            errors.append("MODAL harus lebih dari 0")
        if self.order_usdt is not None and self.order_usdt <= 0:
            errors.append("JUMLAH harus lebih dari 0")
        if not 0 < self.margin_pct <= 100:
            errors.append("MARGIN harus di antara 0 dan 100 persen")
        if not 1 <= self.leverage <= 10:
            errors.append("LEVERAGE harus 1..10")
        if self.max_reentries < 0:
            errors.append("batas masuk ulang tidak boleh negatif")
        if not 0 < self.target_pct < 100:
            errors.append("TARGET harus di antara 0 dan 100 persen")
        tops = (*(self.short_tops or ()), *self.long_tops)
        if any(top not in TOPS for top in tops):
            errors.append("Top untuk short dan long harus 1..5")
        if self.short_tops is not None and not tops:
            errors.append("pilih minimal satu Top untuk short atau long")
        if not 0 < self.long_target_pct < 100:
            errors.append("TARGET LONG harus di antara 0 dan 100 persen")
        if self.stop_pct is not None and not 0 < self.stop_pct < 100:
            errors.append("CUTLOSS harus di antara 0 dan 100 persen")
        if self.min_crosses < 1:
            errors.append("MIN_TURUN minimal 1")
        if self.fee_pct < 0:
            errors.append("BIAYA tidak boleh negatif")
        if self.signal_source not in SIGNAL_SOURCES:
            errors.append(f"SINYAL harus salah satu dari {SIGNAL_SOURCES}")
        if errors:
            raise ConfigError("Pengaturan tidak valid: " + "; ".join(errors))

    def sides_for(self, rank: int) -> tuple[str, ...]:
        """Arah yang boleh dibuka di Top `rank` (kosong = Top ini tidak dimainkan)."""
        short = self.short_tops is None or rank in self.short_tops
        return tuple(
            side for side, ok in (("short", short), ("long", rank in self.long_tops)) if ok
        )

    def side_enabled(self, side: str) -> bool:
        """Arah ini dipakai di setidaknya satu Top."""
        if side == "long":
            return bool(self.long_tops)
        return self.short_tops is None or bool(self.short_tops)

    @property
    def tops(self) -> tuple[int, ...] | None:
        """Top yang dipantau menurut pilihan arah per Top; None = ikut daftar Top biasa."""
        if self.short_tops is None:
            return None
        return tuple(sorted({*self.short_tops, *self.long_tops}))

    def target_for(self, side: str) -> float:
        return self.long_target_pct if side == "long" else self.target_pct

    def breakeven_win_rate(self, loss_pct: float | None = None) -> float:
        """Win rate minimal agar impas (bagian Titik impas).

        `loss_pct` = gerak harga yang ditanggung posisi yang gagal (rata-rata rugi sungguhan).
        Tanpa angka itu dipakai cutloss bila menyala, selain itu contoh STRK 21,8%.
        """
        if loss_pct is None:
            loss_pct = self.stop_pct or REFERENCE_LOSS_PCT
        win = self.target_pct - self.fee_pct
        loss = loss_pct + self.fee_pct
        return loss / (win + loss)
