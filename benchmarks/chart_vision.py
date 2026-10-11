"""Benchmark model visual untuk membaca grafik candlestick lewat gateway OpenAI-compatible.

Kunci jawaban dihitung dari data candle Binance, jadi penilaian otomatis dan gratis.

    python benchmarks/chart_vision.py cases                 # buat grafik + kunci jawaban
    python benchmarks/chart_vision.py smoke                 # 1 grafik per model (cek dukungan gambar)
    python benchmarks/chart_vision.py run --models a,b      # semua grafik pada model terpilih
    python benchmarks/chart_vision.py report results/x.json # ringkasan

Butuh `pip install -e ".[bench]"` dan VIKEY_API_BASE / VIKEY_API_KEY di `.env`.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT / "cases"
RESULTS_DIR = ROOT / "results"
ENV_FILE = ROOT.parent / ".env"
BINANCE = "https://api.binance.com/api/v3"

WINDOW = 60  # jumlah candle yang tampak di grafik
FETCH = 150  # candle yang diambil, supaya MA99 sudah terisi
TOLERANCE = 0.03  # galat angka yang masih dianggap benar, sebagai bagian dari rentang harga
WORKERS = 8

PROMPT = """Ini grafik candlestick dengan tema gelap. Hijau = harga naik, merah = harga turun.
Garis kuning = MA7, magenta = MA25, ungu = MA99. Panel bawah = volume. Sumbu harga ada di kanan.
Baca dari bentuk dan posisi candle terhadap sumbu. Jawab HANYA dengan JSON valid:
{"last_color": "green|red", "prev_color": "green|red",
 "last_close": <angka>, "last_high": <angka termasuk sumbu atas>,
 "window_high": <harga tertinggi di seluruh grafik>,
 "green_count_last5": <berapa candle hijau di 5 candle terakhir>,
 "close_above_ma25": <true|false, apakah candle terakhir ditutup di atas garis magenta>,
 "volume_last_is_max": <true|false, apakah volume candle terakhir tertinggi di panel volume>}"""


# --------------------------------------------------------------------------- util


def load_env() -> dict[str, str]:
    pairs = (line.strip().split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line)
    return {k: v for k, v in pairs}


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------- cases


def pick_cases() -> list[tuple[str, str]]:
    tickers = get_json(f"{BINANCE}/ticker/24hr")
    bad = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
    liquid = [
        t
        for t in tickers
        if t["symbol"].endswith("USDT")
        and not t["symbol"].endswith(bad)
        and float(t["quoteVolume"]) > 5_000_000
    ]
    gainers = [t["symbol"] for t in sorted(liquid, key=lambda t: -float(t["priceChangePercent"]))]
    intervals = ["1d"] * 5 + ["1h"] * 4
    picks = list(zip(gainers[: len(intervals) + 4], [*intervals, *["1d"] * 4], strict=False))
    return picks + [("BTCUSDT", "4h"), ("ETHUSDT", "4h"), ("SOLUSDT", "4h")]


def build_case(symbol: str, interval: str) -> dict[str, Any] | None:
    import matplotlib

    matplotlib.use("Agg")
    import mplfinance as mpf
    import pandas as pd

    rows = get_json(f"{BINANCE}/klines?symbol={symbol}&interval={interval}&limit={FETCH}")
    if len(rows) < FETCH:
        return None
    df = pd.DataFrame(
        [[int(r[0]), *map(float, r[1:6])] for r in rows],
        columns=["t", "Open", "High", "Low", "Close", "Volume"],
    )
    df.index = pd.to_datetime(df.pop("t"), unit="ms")
    for n in (7, 25, 99):
        df[f"ma{n}"] = df["Close"].rolling(n).mean()
    view = df.iloc[-WINDOW:]

    colors = {"ma7": "#f0b90b", "ma25": "#e056c1", "ma99": "#a78bfa"}
    market = mpf.make_marketcolors(up="#2ebd85", down="#f6465d", edge="inherit", wick="inherit", volume="inherit")
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds", marketcolors=market, facecolor="#181a20", figcolor="#181a20",
        gridcolor="#2b3139", y_on_right=True,
    )
    name = f"{symbol}_{interval}"
    CASES_DIR.mkdir(exist_ok=True)
    mpf.plot(
        view, type="candle", style=style, volume=True, figsize=(12, 7),
        addplot=[mpf.make_addplot(view[k], color=c, width=1.1) for k, c in colors.items()],
        savefig={"fname": str(CASES_DIR / f"{name}.png"), "dpi": 100},
    )

    last, prev = view.iloc[-1], view.iloc[-2]
    color = lambda r: "green" if r.Close >= r.Open else "red"  # noqa: E731
    truth = {
        "last_color": color(last),
        "prev_color": color(prev),
        "last_close": float(last.Close),
        "last_high": float(last.High),
        "window_high": float(view.High.max()),
        "green_count_last5": int(sum(color(r) == "green" for r in view.iloc[-5:].itertuples())),
        "close_above_ma25": bool(last.Close > last.ma25),
        "volume_last_is_max": bool(last.Volume >= view.Volume.max()),
    }
    meta = {"name": name, "price_range": float(view.High.max() - view.Low.min()), "truth": truth}
    (CASES_DIR / f"{name}.json").write_text(json.dumps(meta, indent=1))
    return meta


def cmd_cases(_: argparse.Namespace) -> None:
    built = []
    for symbol, interval in pick_cases():
        meta = build_case(symbol, interval)
        if meta:
            built.append(meta["name"])
            print("dibuat:", meta["name"])
    (CASES_DIR / "index.json").write_text(json.dumps(built))
    print(f"{len(built)} kasus di {CASES_DIR}")


def load_cases(limit: int | None = None) -> list[dict[str, Any]]:
    names = json.loads((CASES_DIR / "index.json").read_text())[:limit]
    return [json.loads((CASES_DIR / f"{n}.json").read_text()) for n in names]


# --------------------------------------------------------------------------- model calls


def call_model(
    env: dict[str, str],
    model: str,
    case: str,
    max_tokens: int = 8000,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image = base64.b64encode((CASES_DIR / f"{case}.png").read_bytes()).decode()
    param = "max_tokens"
    started = time.monotonic()
    for _ in range(3):
        body = {
            "model": model,
            param: max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
            ]}],
            **(extra or {}),
        }
        req = urllib.request.Request(
            env["VIKEY_API_BASE"] + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + env["VIKEY_API_KEY"], "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
            usage = data.get("usage") or {}
            return {
                "model": model, "case": case, "ok": True,
                "latency": round(time.monotonic() - started, 2),
                "in_tok": usage.get("prompt_tokens"), "out_tok": usage.get("completion_tokens"),
                "text": data["choices"][0]["message"].get("content") or "",
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if "max_completion_tokens" in detail and param == "max_tokens":
                param = "max_completion_tokens"
            elif "reasoning_exhausted" in detail and max_tokens < 32000:
                max_tokens *= 2
            else:
                return {"model": model, "case": case, "ok": False, "error": f"HTTP {exc.code}: {detail}",
                        "latency": round(time.monotonic() - started, 2)}
        except Exception as exc:  # noqa: BLE001 - jaringan/timeout dilaporkan apa adanya
            return {"model": model, "case": case, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "latency": round(time.monotonic() - started, 2)}
    return {"model": model, "case": case, "ok": False, "error": "gagal setelah 3 percobaan"}


# --------------------------------------------------------------------------- scoring


def as_number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return None


def as_bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    return {"true": True, "false": False}.get(text)


def score(text: str, meta: dict[str, Any]) -> dict[str, bool] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        answer = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    truth, tol = meta["truth"], TOLERANCE * meta["price_range"]
    result: dict[str, bool] = {}
    for key in ("last_color", "prev_color"):
        result[key] = str(answer.get(key, "")).strip().lower() == truth[key]
    for key in ("last_close", "last_high", "window_high"):
        got = as_number(answer.get(key))
        result[key] = got is not None and abs(got - truth[key]) <= tol
    got_n = as_number(answer.get("green_count_last5"))
    result["green_count_last5"] = got_n is not None and int(got_n) == truth["green_count_last5"]
    for key in ("close_above_ma25", "volume_last_is_max"):
        result[key] = as_bool(answer.get(key)) is truth[key]
    return result


# --------------------------------------------------------------------------- commands


def run_many(
    env: dict[str, str],
    models: list[str],
    cases: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
    workers: int = WORKERS,
) -> list[dict[str, Any]]:
    jobs = [(m, c["name"]) for m in models for c in cases]
    by_name = {c["name"]: c for c in cases}
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda j: call_model(env, *j, extra=extra), jobs))
    for r in results:
        if r["ok"]:
            r["scores"] = score(r["text"], by_name[r["case"]])
    return results


def save(results: list[dict[str, Any]], label: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{label}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    return path


def list_models(env: dict[str, str]) -> list[str]:
    req = urllib.request.Request(env["VIKEY_API_BASE"] + "/models",
                                 headers={"Authorization": "Bearer " + env["VIKEY_API_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return sorted(m["id"] for m in json.load(resp)["data"])


def resolve_models(env: dict[str, str], spec: str | None, exclude: str | None) -> list[str]:
    models = list_models(env)
    if spec:
        wanted = spec.split(",")
        models = [m for m in models if any(w == m or w in m for w in wanted)]
    if exclude:
        models = [m for m in models if not any(x in m for x in exclude.split(","))]
    return models


def cmd_smoke(args: argparse.Namespace) -> None:
    env = load_env()
    models = resolve_models(env, args.models, args.exclude)
    cases = load_cases(1)
    print(f"smoke test: {len(models)} model x 1 grafik")
    results = run_many(env, models, cases)
    for r in sorted(results, key=lambda r: r["model"]):
        if r["ok"]:
            flag = "format-salah" if r.get("scores") is None else f"{sum(r['scores'].values())}/8"
            print(f"  OK   {r['model']:<40} {r['latency']:>6}s in={r['in_tok']} out={r['out_tok']} {flag}")
        else:
            print(f"  GAGAL {r['model']:<39} {r['error'][:110]}")
    print("disimpan:", save(results, "smoke"))


def cmd_run(args: argparse.Namespace) -> None:
    env = load_env()
    models = resolve_models(env, args.models, args.exclude)
    cases = load_cases(args.cases)
    print(f"{len(models)} model x {len(cases)} grafik = {len(models) * len(cases)} panggilan")
    extra = json.loads(args.extra) if args.extra else None
    path = save(run_many(env, models, cases, extra, args.workers), args.label)
    print("disimpan:", path)
    print_report(json.loads(path.read_text()))


def print_report(results: list[dict[str, Any]]) -> None:
    rows = []
    for model in sorted({r["model"] for r in results}):
        mine = [r for r in results if r["model"] == model]
        scored = [r["scores"] for r in mine if r.get("scores")]
        correct = sum(sum(s.values()) for s in scored)
        done = [r for r in mine if r["ok"]]
        rows.append({
            "model": model,
            "acc": 100 * correct / (8 * len(mine)) if mine else 0.0,
            "api_err": len(mine) - len(done),
            "fmt_err": len(done) - len(scored),
            "lat": statistics.median(r["latency"] for r in done) if done else float("nan"),
            "in": statistics.mean(r["in_tok"] or 0 for r in done) if done else 0,
            "out": statistics.mean(r["out_tok"] or 0 for r in done) if done else 0,
        })
    print(f"{'model':<40}{'akurasi':>9}{'api_err':>8}{'fmt_err':>8}{'med_detik':>10}{'tok_in':>8}{'tok_out':>8}")
    for r in sorted(rows, key=lambda r: -r["acc"]):
        print(f"{r['model']:<40}{r['acc']:>8.1f}%{r['api_err']:>8}{r['fmt_err']:>8}"
              f"{r['lat']:>10.1f}{r['in']:>8.0f}{r['out']:>8.0f}")


def cmd_report(args: argparse.Namespace) -> None:
    print_report(json.loads(Path(args.file).read_text()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases").set_defaults(fn=cmd_cases)
    for name, fn in (("smoke", cmd_smoke), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--models", help="id model dipisah koma (cocok sebagian); default semua")
        p.add_argument("--exclude", help="kata kunci model yang dilewati, dipisah koma")
        if name == "run":
            p.add_argument("--cases", type=int, help="batasi jumlah grafik")
            p.add_argument("--extra", help='JSON parameter tambahan untuk request, mis. \'{"reasoning_effort":"low"}\'')
            p.add_argument("--workers", type=int, default=WORKERS, help="1 = berurutan (ukur kecepatan)")
            p.add_argument("--label", default="run", help="awalan nama file hasil")
        p.set_defaults(fn=fn)
    report = sub.add_parser("report")
    report.add_argument("file")
    report.set_defaults(fn=cmd_report)
    args = parser.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
