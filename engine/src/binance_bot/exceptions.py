class BotError(Exception):
    """Basis semua error yang sengaja dilempar oleh bot."""


class ConfigError(BotError):
    """Konfigurasi yang dibutuhkan belum lengkap (mis. kunci API di `.env`)."""


class CommandError(BotError):
    """Perintah sistem (mis. `open`, `lsappinfo`) gagal dijalankan."""


class AppLaunchError(BotError):
    """Aplikasi gagal dibuka."""


class AppNotRunningError(BotError):
    """Aplikasi harus sudah berjalan (dan login) sebelum workflow ini dijalankan."""


class AppTimeoutError(BotError):
    """Aplikasi tidak menjadi jendela aktif dalam batas waktu yang ditentukan."""


class WindowError(BotError):
    """Membaca, mengklik, atau menangkap jendela gagal (biasanya karena izin macOS)."""


class ScreenReadError(BotError):
    """Teks yang dibutuhkan (mis. nama koin) tidak terbaca dari layar."""


class PositionNotFoundError(ScreenReadError):
    """Baris posisi koin tidak ada di tab Posisi bursa (mis. sudah ditutup manual)."""


class AnalysisError(BotError):
    """Analisis grafik oleh model gagal atau jawabannya tidak sesuai skema."""


class HubError(BotError):
    """Hub (berbagi hasil antar laptop) tidak bisa dihubungi atau menolak permintaan."""


class SafetyError(BotError):
    """Aksi ditolak demi keamanan, mis. klik ke area tombol order saat beli dimatikan."""


class MarketDataError(BotError):
    """Data pasar publik Binance (harga, funding, candle) tidak bisa diambil."""


class NoHistoryError(MarketDataError):
    """Bursa ini memang tidak punya riwayat harga (candle/funding), mis. Tebbit lewat layar.

    Berbeda dengan Binance yang diblokir sementara: posisi tetap boleh ditutup di harga terkini.
    """
