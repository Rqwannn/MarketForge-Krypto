# Perintah cepat engine SOP "Short Top Gainers (Futures 1x)". Ketik `make` untuk daftar perintah.
# Contoh:
#   make single MODAL=100
#   make single MODAL=100 RANKS=1 SL=4 TARGET=3
#   make single JUMLAH=150 RANKS=2
#   make leader RANKS=1,2,3 INTERVAL=15
#   make follower HUB=http://192.168.1.24:8765 RANK=2 MODAL=100
#   make jurnal
# Tombol order TIDAK pernah ditekan: setiap posisi dicatat sebagai uji kertas (dry run).

VENV   ?= .venv
PYTHON ?= python3
BOT     = $(VENV)/bin/binance-bot

# Mode dan rank.
RANK     ?= 1
RANKS    ?= 1,2,3
INTERVAL ?= 0
HUB      ?=
PORT     ?=
# Parameter SOP (default = angka di PDF; yang bertanda usulan perlu disepakati).
MODAL       ?=
JUMLAH      ?=
RISIKO      ?= 1
SL          ?= 5
TARGET      ?= 4
MIN_NAIK    ?= 30
MIN_TANDA   ?= 2
BATAS_JAM   ?= 4
MAKS_POSISI ?= 1
SINYAL      ?= ai
NO_FILL     ?=
# Benchmark.
CASES  ?= 12
MODELS ?=

SOP_ARGS = $(if $(MODAL),--modal $(MODAL)) $(if $(JUMLAH),--jumlah $(JUMLAH)) \
	--risiko $(RISIKO) --sl $(SL) --target $(TARGET) --min-naik $(MIN_NAIK) \
	--min-tanda $(MIN_TANDA) --batas-jam $(BATAS_JAM) --maks-posisi $(MAKS_POSISI) \
	--sinyal $(SINYAL) $(if $(NO_FILL),--no-fill)

.DEFAULT_GOAL := help
.PHONY: help install env token fix-hidden window-size hub-health \
	open single single-fast leader follower jurnal uji-isi \
	test lint format typecheck check bench-install bench-cases bench-smoke bench-run clean

help: ## Tampilkan daftar perintah
	@echo "Engine SOP Short Top Gainers (Futures 1x) - perintah yang tersedia:"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Parameter SOP: MODAL=$(MODAL) JUMLAH=$(JUMLAH) RISIKO=$(RISIKO) SL=$(SL) TARGET=$(TARGET)"
	@echo "               MIN_NAIK=$(MIN_NAIK) MIN_TANDA=$(MIN_TANDA) BATAS_JAM=$(BATAS_JAM) MAKS_POSISI=$(MAKS_POSISI) SINYAL=$(SINYAL)"
	@echo "Mode (rank 1..5): RANK=$(RANK) RANKS=$(RANKS) INTERVAL=$(INTERVAL) HUB=$(HUB) PORT=$(PORT)"
	@echo "Panduan: docs/SOP.md, docs/MODE_SINGLE.md, docs/MODE_BANYAK.md"

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

window-size: ## Cek ukuran jendela Binance di laptop ini (harus 1470x859 pt)
	@open -b com.binance.BinanceDesktop && sleep 1
	@osascript -e 'tell application "System Events" to tell process "Binance" to get size of window 1' \
	| awk -F', ' '{ ok = ($$1 >= 1441 && $$1 <= 1499 && $$2 >= 842 && $$2 <= 876) ? "OK" : "BERBEDA, sesuaikan ukuran jendela"; \
	  printf "Jendela Binance: %sx%s pt (harus 1470x859): %s\n", $$1, $$2, ok }'

hub-health: ## Cek koneksi laptop ini ke hub leader (HUB=http://IP:8765)
	$(if $(HUB),,$(error Isi HUB, mis. make hub-health HUB=http://192.168.1.24:8765))
	@curl -s -m 5 $(HUB)/health && echo "  <- hub bisa dihubungi" \
	|| echo "Hub $(HUB) tidak bisa dihubungi: cek IP, WiFi yang sama, dan firewall leader"

# --------------------------------------------------------------------------- menjalankan SOP

open: ## Buka Binance jika belum berjalan (sesi login tidak diganggu)
	$(BOT) open

single: ## SOP penuh di satu laptop (MODAL= atau JUMLAH=, RANKS=1..5)
	$(BOT) single --ranks $(RANKS) $(SOP_ARGS)

single-fast: ## Sama dengan single, AI tanpa thinking (lebih cepat, kurang teliti)
	BOT_ANALYZER_THINKING=false $(BOT) single --ranks $(RANKS) $(SOP_ARGS)

leader: ## Mode banyak, leader: AI tanda pucuk sekali per koin, bagikan lewat hub
	$(BOT) leader --ranks $(RANKS) --min-naik $(MIN_NAIK) --interval $(INTERVAL) $(if $(PORT),--port $(PORT))

follower: ## Mode banyak, follower: SOP penuh pakai hasil AI dari HUB (RANK=1..5, MODAL=)
	$(BOT) follower --rank $(RANK) $(if $(HUB),--hub $(HUB)) $(SOP_ARGS)

jurnal: ## Nilai uji kertas dan rekap win rate terhadap titik impas SOP
	$(BOT) jurnal $(SOP_ARGS)

uji-isi: ## Uji kalibrasi: buka top gainer RANK lalu isi kolom Jumlah (JUMLAH=1)
	$(if $(JUMLAH),,$(error Isi JUMLAH, mis. make uji-isi RANK=1 JUMLAH=1))
	$(BOT) uji-isi --rank $(RANK) --jumlah $(JUMLAH)

# --------------------------------------------------------------------------- pengembangan

test: ## Jalankan semua tes
	$(VENV)/bin/pytest -q

lint: ## Cek gaya dan format kode
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests

format: ## Rapikan format kode otomatis
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

typecheck: ## Cek tipe (mypy strict)
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
