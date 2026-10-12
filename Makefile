# Perintah dari root repo. Target engine diteruskan ke engine/Makefile (variabel ikut terbawa),
# jadi `make single MODAL=100` tetap jalan dari sini. Daftar lengkap target engine: `make -C engine`.
#   make app-install   # sekali: pasang Electron
#   make app           # buka aplikasi desktop
#   make check         # semua pemeriksaan engine + interface

ENGINE_TARGETS = install env token fix-hidden window-size hub-health \
	open cek single single-fast leader follower jurnal uji-isi \
	test lint format typecheck bench-install bench-cases bench-smoke bench-run clean

.DEFAULT_GOAL := help
.PHONY: help app-install app app-test check $(ENGINE_TARGETS)

help: ## Tampilkan daftar perintah
	@echo "Aplikasi (interface/):"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@$(MAKE) --no-print-directory -C engine help

$(ENGINE_TARGETS):
	@$(MAKE) --no-print-directory -C engine $@

app-install: ## Pasang Electron untuk aplikasi desktop (sekali)
	cd interface && npm ci

app: ## Buka aplikasi desktop (butuh `make install` dan `make app-install`)
	cd interface && npm start

app-test: ## Tes interface (node:test, tanpa membuka jendela)
	cd interface && npm test

check: ## Semua pemeriksaan: engine (lint + tipe + tes) dan interface
	@$(MAKE) --no-print-directory -C engine check
	@$(MAKE) --no-print-directory app-test
