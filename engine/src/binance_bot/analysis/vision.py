"""Klien model visual di gateway OpenAI-compatible (vikey): kirim gambar + prompt, terima teks."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError, ConfigError

PostJson = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def _post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result: dict[str, Any] = json.load(response)
            return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise AnalysisError(f"Gateway menolak permintaan (HTTP {exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AnalysisError(f"Gagal menghubungi gateway analisis: {exc}") from exc


def extract_json(text: str) -> Any:
    """Ambil objek JSON dari jawaban model (boleh dibungkus ```json)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise AnalysisError(f"Jawaban model bukan JSON: {text[:200]!r}")
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"JSON jawaban model rusak: {text[:200]!r}") from exc


class VisionClient:
    def __init__(self, settings: Settings, *, post: PostJson = _post_json) -> None:
        if not settings.vikey_api_base or not settings.vikey_api_key:
            raise ConfigError("VIKEY_API_BASE dan VIKEY_API_KEY harus diisi di .env")
        self._settings = settings
        self._post = post

    def ask(self, image: Path, prompt: str) -> str:
        encoded = base64.b64encode(image.read_bytes()).decode()
        thinking = self._settings.analyzer_thinking
        body = {
            "model": self._settings.analyzer_model,
            # Token berpikir ikut dihitung: batas kecil membuat jawaban kosong.
            "max_tokens": 4000 if thinking else 300,
            **({} if thinking else {"thinking": {"type": "disabled"}}),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._settings.vikey_api_key}",
            "Content-Type": "application/json",
        }
        response = self._post(
            f"{self._settings.vikey_api_base}/chat/completions",
            headers,
            body,
            self._settings.analyzer_timeout_s,
        )
        try:
            return str(response["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError(
                f"Format respons gateway tidak dikenal: {str(response)[:200]}"
            ) from exc
