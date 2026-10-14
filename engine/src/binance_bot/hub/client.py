from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from binance_bot.analysis import AnalysisRecord
from binance_bot.exceptions import ConfigError, HubError


@dataclass(frozen=True, slots=True)
class SharedAnalysis:
    record: AnalysisRecord
    age_s: float  # dihitung dengan jam hub


@dataclass(frozen=True, slots=True)
class LeaderPlan:
    ranks: tuple[int, ...]  # Top yang dimainkan leader di putaran ini
    done: bool  # leader sudah selesai menilai semuanya
    age_s: float  # umur putaran, dihitung dengan jam hub


class HubClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 10.0) -> None:
        if not base_url:
            raise ConfigError("Alamat hub belum diisi: pakai --hub http://IP:PORT atau BOT_HUB_URL")
        if not token:
            raise ConfigError("BOT_HUB_TOKEN wajib diisi di .env, sama dengan di laptop leader")
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s

    def list(self) -> list[SharedAnalysis]:
        payload = self._get("/analyses")
        records = payload.get("records")
        if not isinstance(records, list):
            raise HubError("Respons hub tidak berisi daftar hasil")
        return [self._shared(item, payload) for item in records]

    def get(self, symbol: str) -> SharedAnalysis | None:
        query = urllib.parse.urlencode({"symbol": symbol})
        payload = self._get(f"/analyses?{query}", allow_missing=True)
        return None if payload is None else self._shared(payload.get("record"), payload)

    def plan(self) -> LeaderPlan:
        """Rencana putaran leader: Top mana yang dimainkan dan apakah putaran sudah selesai."""
        payload = self._get("/analyses?plan=1")
        ranks, done = payload.get("ranks"), payload.get("done")
        now, started = payload.get("now"), payload.get("started")
        valid = isinstance(ranks, list) and all(isinstance(r, int) for r in ranks)
        if not valid or not isinstance(done, bool):
            raise HubError("Respons hub tidak berisi rencana putaran")
        if not isinstance(now, int | float) or not isinstance(started, int | float):
            raise HubError("Respons hub tidak berisi waktu putaran")
        return LeaderPlan(tuple(ranks), done, float(now) - float(started))

    def by_rank(self, rank: int) -> SharedAnalysis | None:
        """Hasil leader untuk Top `rank` di putaran ini, atau None bila belum dinilai."""
        payload = self._get(f"/analyses?rank={int(rank)}", allow_missing=True)
        return None if payload is None else self._shared(payload.get("record"), payload)

    def _shared(self, item: Any, payload: dict[str, Any]) -> SharedAnalysis:
        record = AnalysisRecord.from_dict(item)
        now = payload.get("now")
        if not isinstance(now, int | float):
            raise HubError("Respons hub tidak berisi waktu hub")
        return SharedAnalysis(record, age_s=float(now) - record.analyzed_at)

    def _get(self, path: str, *, allow_missing: bool = False) -> Any:
        request = urllib.request.Request(
            self._base + path, headers={"Authorization": f"Bearer {self._token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and allow_missing:
                return None
            if exc.code == 401:
                raise HubError("Hub menolak token: samakan BOT_HUB_TOKEN dengan leader") from exc
            raise HubError(f"Hub menjawab HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise HubError(
                f"Hub {self._base} tidak bisa dihubungi ({exc}). Pastikan leader berjalan, "
                "laptop di WiFi yang sama, dan firewall macOS leader mengizinkan Python."
            ) from exc
        except ValueError as exc:
            raise HubError("Respons hub bukan JSON") from exc
