# Engine

Engine Python untuk SOP V2 "Short Top Gainers (Futures 2x)": navigasi Binance Desktop, pembacaan
pola garis kuning dengan AI, saringan SOP, ukuran posisi, jurnal uji kertas, dan hub LAN.
Dipakai oleh aplikasi desktop (`../interface`) lewat CLI `binance-bot`, dan bisa dijalankan
langsung dari terminal untuk debugging.

Panduan lengkap: [../README.md](../README.md), [../docs/SOP.md](../docs/SOP.md),
[../docs/MODE_SINGLE.md](../docs/MODE_SINGLE.md), [../docs/MODE_BANYAK.md](../docs/MODE_BANYAK.md).

## Kontrak dengan interface

| Perintah | Keluaran di stdout |
|---|---|
| `binance-bot --events single/leader/follower ...` | Satu JSON per baris: `{"ts", "level", "logger", "message"}`, plus `"event"` untuk kejadian penting (`coin`, `cycle`, `hub`) |
| `binance-bot jurnal --json` | Satu JSON: rekap (`stats`) dan trade terakhir (`trades`) |
| `binance-bot cek` | Satu JSON: daftar `{"id", "ok", "pesan"}` kesiapan laptop |

Berhenti dengan SIGINT (Ctrl+C), kode keluar 130. File runtime (`.env`, `journal/`, `logs/`,
`screenshots/`) ada di folder ini.
