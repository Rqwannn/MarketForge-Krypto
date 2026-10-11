"""Hub LAN: leader menyajikan hasil analisis ke laptop lain lewat HTTP (hanya-baca).

Setiap permintaan data wajib membawa token yang sama dengan leader, karena nantinya hasil ini
dipakai untuk keputusan beli: laptop lain di WiFi yang sama tidak boleh membaca atau meniru hub.
"""

from __future__ import annotations

import hmac
import json
import logging
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from binance_bot.exceptions import ConfigError, HubError
from binance_bot.hub.store import AnalysisStore

logger = logging.getLogger(__name__)


def lan_ip() -> str:
    """IP laptop ini di jaringan lokal (UDP connect tidak mengirim paket apa pun)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return str(sock.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def _handler_for(
    store: AnalysisStore, token: str, clock: Callable[[], float]
) -> type[BaseHTTPRequestHandler]:
    expected = f"Bearer {token}".encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "BinanceBotHub/1"

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/health":
                self._send(200, {"status": "ok"})
                return
            supplied = self.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(supplied, expected):
                self._send(401, {"error": "token hub salah atau tidak ada"})
                return
            if url.path != "/analyses":
                self._send(404, {"error": "alamat tidak dikenal"})
                return

            # `now` dari jam hub, agar umur analisis benar walau jam tiap laptop berbeda.
            now = clock()
            symbol = parse_qs(url.query).get("symbol", [None])[0]
            if symbol is None:
                self._send(200, {"now": now, "records": [r.to_dict() for r in store.all()]})
                return
            record = store.get(symbol)
            if record is None:
                self._send(404, {"error": f"belum ada analisis untuk {symbol}"})
                return
            self._send(200, {"now": now, "record": record.to_dict()})

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("hub %s - " + format, self.client_address[0], *args)

    return Handler


class HubServer:
    def __init__(
        self,
        store: AnalysisStore,
        token: str,
        *,
        host: str = "0.0.0.0",
        port: int = 8765,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not token:
            raise ConfigError("BOT_HUB_TOKEN wajib diisi di .env, dan sama di semua laptop")
        self._store = store
        self._token = token
        self._host = host
        self._port = port
        self._clock = clock
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        try:
            self._server = ThreadingHTTPServer(
                (self._host, self._port), _handler_for(self._store, self._token, self._clock)
            )
        except OSError as exc:
            raise HubError(f"Hub tidak bisa memakai port {self._port}: {exc}") from exc
        threading.Thread(target=self._server.serve_forever, name="hub", daemon=True).start()
        logger.info("Hub berjalan. Di laptop lain pakai: --hub %s", self.url)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._port

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}"
