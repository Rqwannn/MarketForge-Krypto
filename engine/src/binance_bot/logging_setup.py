from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def event(kind: str, **fields: Any) -> dict[str, dict[str, Any]]:
    """`extra` untuk log yang juga menjadi kejadian terstruktur bagi aplikasi desktop.

    Contoh: `logger.info("...", extra=event("coin", symbol="WUSDT"))`.
    """
    return {"event": {"type": kind, **fields}}


class JsonLinesFormatter(logging.Formatter):
    """Satu JSON per baris (dibaca aplikasi desktop lewat stdout)."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload = getattr(record, "event", None)
        if isinstance(payload, dict):
            data["event"] = payload
        if record.exc_info:
            data["error"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging(level: str, log_dir: Path, *, events: bool = False) -> None:
    """Log ke konsol dan ke file `bot.log` (rotasi 1 MB x 3 file).

    Dengan `events`, konsol diganti JSON per baris di stdout untuk aplikasi desktop.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)

    if events:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(JsonLinesFormatter())
    else:
        console = logging.StreamHandler()
        console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)
