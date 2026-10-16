# Perintah cepat engine SOP V2 "Short Top Gainers (Futures 2x)". Ketik `make` untuk daftar perintah.
# Contoh:
#   make single MODAL=100                      # pantau top 5, masuk bila pola garis kuning OK
#   make single MODAL=100 INTERVAL=5           # pantau ulang tiap 5 menit
#   make single MODAL=100 RANKS=1,2 TARGET=1   # hanya top 1-2, target 1%
#   make single JUMLAH=150 RANKS=2           # ukuran order manual 150 USDT
#   make leader INTERVAL=15
#   make follower HUB=http://192.168.1.24:8765 RANK=2 MODAL=100
#   make jurnal
# Tombol order TIDAK pernah ditekan: setiap posisi dicatat sebagai uji kertas (dry run).

VENV   ?= .venv
PYTHON ?= python3
BOT     = $(VENV)/bin/binance-bot

# Mode dan rank.
RANK     ?= 1
RANKS    ?= 1,2,3,4,5
INTERVAL ?= 0
HUB      ?=
PORT     ?=
# Parameter SOP V3 (tanpa stop-loss dan batas waktu; jual otomatis di TARGET %).
MODAL       ?=
JUMLAH      ?=
MARGIN      ?= 50
LEVERAGE    ?= 2
TARGET      ?= 3
MIN_TURUN   ?= 2
MIN_NAIK    ?= 0
SINYAL      ?= ai
NO_FILL     ?=
# Benchmark.
CASES  ?= 12
MODELS ?=

SOP_ARGS = $(if $(MODAL),--modal $(MODAL)) $(if $(JUMLAH),--jumlah $(JUMLAH)) \
	--margin $(MARGIN) --leverage $(LEVERAGE) --target $(TARGET) \
	--min-turun $(MIN_TURUN) --min-naik $(MIN_NAIK) \
	--sinyal $(SINYAL) $(if $(NO_FILL),--no-fill)

.DEFAULT_GOAL := help
.PHONY: help install env token fix-hidden window-size hub-health \
	open cek single single-fast leader follower jurnal uji-isi \
	test lint format typecheck check bench-install bench-cases bench-smoke bench-run clean

help: ## Tampilkan daftar perintah
	@echo "Engine SOP V3 Short Top Gainers (Futures 2x) - perintah yang tersedia:"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Parameter SOP V3: MODAL=$(MODAL) JUMLAH=$(JUMLAH) MARGIN=$(MARGIN) LEVERAGE=$(LEVERAGE) TARGET=$(TARGET)"
	@echo "                  MIN_TURUN=$(MIN_TURUN) MIN_NAIK=$(MIN_NAIK) SINYAL=$(SINYAL)"
	@echo "Mode (rank 1..5): RANK=$(RANK) RANKS=$(RANKS) INTERVAL=$(INTERVAL) HUB=$(HUB) PORT=$(PORT)"
	@echo "Panduan: ../docs/SOP.md, ../docs/MODE_SINGLE.md, ../docs/MODE_BANYAK.md"

# --------------------------------------------------------------------------- setup

install: ## Buat .venv dan pasang bot beserta alat pengembangan
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q -e ".[dev]"
	@$(MAKE) --no-print-directory fix-hidden
	@echo "Selesai. Lanjut: make env"

env: ## Buat .env dari .env.example (tidak menimpa .env yang sudah ada)
	@if [ -f .env ]; then echo ".env sudah ada, tidak diubah"; \
	else cp .env.example .env && echo ".env dibuat. Buka dan isi nilainya."; fi

token: ## Buat token acak untuk BOT_HUB_TOKEN (pakai yang sama di semua laptop)
	@openssl rand -hex 16

fix-hidden: ## Perbaiki error "No module named binance_bot" (flag hidden macOS)
	@chflags -R nohidden $(VENV) src 2>/dev/null || true

window-size: ## Lihat ukuran jendela Binance (bot mengaturnya otomatis ke 1470x859 pt)
	@open -b com.binance.BinanceDesktop && sleep 1
	@osascript -e 'tell application "System Events" to tell process "Binance" to get size of window 1' \
	| awk -F', ' '{ ok = ($$1 >= 1441 && $$1 <= 1499 && $$2 >= 842 && $$2 <= 876) ? "OK" : "BERBEDA (diatur otomatis saat bot mulai)"; \
	  printf "Jendela Binance: %sx%s pt (harus 1470x859): %s\n", $$1, $$2, ok }'

hub-health: ## Cek koneksi laptop ini ke hub leader (HUB=http://IP:8765)
	$(if $(HUB),,$(error Isi HUB, mis. make hub-health HUB=http://192.168.1.24:8765))
	@curl -s -m 5 $(HUB)/health && echo "  <- hub bisa dihubungi" \
	|| echo "Hub $(HUB) tidak bisa dihubungi: cek IP, WiFi yang sama, dan firewall leader"

# --------------------------------------------------------------------------- menjalankan SOP

open: fix-hidden ## Buka Binance jika belum berjalan (sesi login tidak diganggu)
	$(BOT) open

cek: fix-hidden ## Cek kesiapan laptop ini (Binance, jendela, izin layar, API, .env) dalam JSON
	$(BOT) cek

single: fix-hidden ## SOP V2 di satu laptop: pantau top 5, masuk bila pola OK (MODAL=, INTERVAL=)
	$(BOT) single --ranks $(RANKS) --interval $(INTERVAL) $(SOP_ARGS)

single-fast: fix-hidden ## Sama dengan single, AI tanpa thinking (lebih cepat, kurang teliti menghitung)
	BOT_ANALYZER_THINKING=false $(BOT) single --ranks $(RANKS) --interval $(INTERVAL) $(SOP_ARGS)

leader: fix-hidden ## Mode banyak, leader: AI baca pola garis kuning sekali per koin, bagikan lewat hub
	$(BOT) leader --ranks $(RANKS) --min-naik $(MIN_NAIK) --min-turun $(MIN_TURUN) --interval $(INTERVAL) $(if $(PORT),--port $(PORT))

follower: fix-hidden ## Mode banyak, follower: SOP penuh pakai hasil AI dari HUB (RANK=1..5, MODAL=)
	$(BOT) follower --rank $(RANK) $(if $(HUB),--hub $(HUB)) $(SOP_ARGS)

jurnal: fix-hidden ## Nilai uji kertas dan rekap win rate terhadap titik impas SOP
	$(BOT) jurnal $(SOP_ARGS)

uji-isi: fix-hidden ## Uji kalibrasi: buka top gainer RANK lalu isi kolom Jumlah (JUMLAH=1)
	$(if $(JUMLAH),,$(error Isi JUMLAH, mis. make uji-isi RANK=1 JUMLAH=1))
	$(BOT) uji-isi --rank $(RANK) --jumlah $(JUMLAH)

# --------------------------------------------------------------------------- pengembangan

test: fix-hidden ## Jalankan semua tes
	$(VENV)/bin/pytest -q

lint: ## Cek gaya dan format kode
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests

format: ## Rapikan format kode otomatis
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

typecheck: fix-hidden ## Cek tipe (mypy strict)
	$(VENV)/bin/mypy

check: lint typecheck test ## Semua pemeriksaan (lint + tipe + tes)

# --------------------------------------------------------------------------- benchmark model AI

bench-install: ## Pasang pustaka grafik untuk benchmark
	$(VENV)/bin/pip install -q -e ".[bench]"
	@$(MAKE) --no-print-directory fix-hidden

bench-cases: ## Benchmark: buat grafik uji + kunci jawaban dari data Binance
	$(VENV)/bin/python benchmarks/chart_vision.py cases

bench-smoke: ## Benchmark: 1 grafik per model (cek mana yang menerima gambar)
	$(VENV)/bin/python benchmarks/chart_vision.py smoke

bench-run: ## Benchmark: CASES grafik pada MODELS (kosong = semua model)
	$(VENV)/bin/python benchmarks/chart_vision.py run --cases $(CASES) $(if $(MODELS),--models $(MODELS))

clean: ## Hapus cache (screenshots, logs, journal, .env, dan .venv tidak disentuh)
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
