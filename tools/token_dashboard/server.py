#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_DIR = ROOT / "observations"
STATIC_DIR = Path(__file__).resolve().parent / "static"

TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

PRICING: list[dict[str, Any]] = [
    {
        "provider": "openai",
        "model": "gpt-5.5",
        "match": "exact",
        "input_per_mtok": 5.00,
        "cached_input_per_mtok": 0.50,
        "output_per_mtok": 30.00,
        "source": "https://openai.com/api/pricing/",
    },
    {
        "provider": "openai",
        "model": "gpt-5.4",
        "match": "exact",
        "input_per_mtok": 2.50,
        "cached_input_per_mtok": 0.25,
        "output_per_mtok": 15.00,
        "source": "https://openai.com/api/pricing/",
    },
    {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "match": "exact",
        "input_per_mtok": 0.75,
        "cached_input_per_mtok": 0.075,
        "output_per_mtok": 4.50,
        "source": "https://openai.com/api/pricing/",
    },
    {
        "provider": "google",
        "model": "gemini-3-flash-preview",
        "match": "exact",
        "input_per_mtok": 0.50,
        "cached_input_per_mtok": 0.00,
        "output_per_mtok": 3.00,
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    {
        "provider": "google",
        "model": "gemini-3-flash",
        "match": "exact",
        "input_per_mtok": 0.50,
        "cached_input_per_mtok": 0.00,
        "output_per_mtok": 3.00,
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    {
        "provider": "anthropic",
        "model": "claude-sonnet-4",
        "match": "prefix",
        "input_per_mtok": 3.00,
        "cached_input_per_mtok": 0.30,
        "output_per_mtok": 15.00,
        "source": "https://docs.anthropic.com/en/docs/about-claude/pricing",
    },
]


@dataclass(frozen=True)
class UsagePart:
    provider: str
    model: str
    role: str
    usage: dict[str, int]
    cost_usd: float | None
    pricing_model: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def empty_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def normalize_usage(source: Any) -> dict[str, int]:
    usage = empty_usage()
    if not isinstance(source, dict):
        return usage
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens", "prompt_token_count", "input_token_count"),
        "output_tokens": (
            "output_tokens",
            "completion_tokens",
            "candidates_token_count",
            "output_token_count",
        ),
        "total_tokens": ("total_tokens", "total_token_count"),
        "reasoning_tokens": ("reasoning_tokens", "thinking_tokens", "thoughts_token_count"),
        "cache_read_input_tokens": ("cache_read_input_tokens", "cached_tokens"),
        "cache_creation_input_tokens": ("cache_creation_input_tokens",),
    }
    for canonical, names in aliases.items():
        for name in names:
            value = to_int(source.get(name))
            if value:
                usage[canonical] = value
                break
    if not usage["total_tokens"] and (usage["input_tokens"] or usage["output_tokens"]):
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def add_usage(target: dict[str, int], source: dict[str, int]) -> None:
    for key in TOKEN_KEYS:
        target[key] += to_int(source.get(key))


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_path(value: str, csv_path: Path) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    scoped = (csv_path.parent / candidate).resolve()
    if scoped.exists():
        return scoped
    rooted = (ROOT / candidate).resolve()
    if rooted.exists():
        return rooted
    return rooted


def started_at(row: dict[str, str], result: dict[str, Any], csv_path: Path) -> str:
    direct = row.get("started_at_utc") or row.get("timestamp") or result.get("timestamp") or ""
    if direct:
        return str(direct)
    parent = csv_path.parent.name
    stamp = parent.split("_", 1)[0]
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ""


def role_trace(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    trace: dict[str, dict[str, str]] = {}
    raw = result.get("role_model_trace")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").strip()
            if role:
                trace[role] = {
                    "provider": str(entry.get("provider") or "").strip(),
                    "model": str(entry.get("model") or "").strip(),
                }
    return trace


def provider_for_model(model: str, fallback: str = "") -> str:
    lowered = model.lower()
    if lowered.startswith("gpt-") or lowered.startswith("o"):
        return "openai"
    if lowered.startswith("gemini"):
        return "google"
    if lowered.startswith("claude"):
        return "anthropic"
    return fallback


def role_model(result: dict[str, Any], trace: dict[str, dict[str, str]], role: str) -> tuple[str, str]:
    aliases = [role]
    if role == "planner":
        aliases.append("single_agent")
    for alias in aliases:
        entry = trace.get(alias)
        if entry and entry.get("model"):
            return entry.get("provider") or provider_for_model(entry["model"]), entry["model"]
    model = str(result.get(f"{role}_model") or result.get("planner_model") or "").strip()
    provider = str(result.get(f"{role}_provider") or "").strip()
    if model:
        return provider or provider_for_model(model), model
    return "", ""


def match_price(model: str) -> dict[str, Any] | None:
    lowered = model.lower()
    for price in PRICING:
        candidate = str(price["model"]).lower()
        if price.get("match") == "prefix" and lowered.startswith(candidate):
            return price
        if lowered == candidate:
            return price
    return None


def calculate_cost(model: str, usage: dict[str, int]) -> tuple[float | None, str | None]:
    price = match_price(model)
    if not price:
        return None, None
    cached = min(usage["cache_read_input_tokens"], usage["input_tokens"])
    uncached_input = max(usage["input_tokens"] - cached, 0)
    cost = (
        uncached_input * float(price["input_per_mtok"])
        + cached * float(price["cached_input_per_mtok"])
        + usage["output_tokens"] * float(price["output_per_mtok"])
    ) / 1_000_000
    return cost, str(price["model"])


def top_level_usage(row: dict[str, str], result: dict[str, Any]) -> dict[str, int]:
    usage = normalize_usage(
        {
            "input_tokens": row.get("llm_input_tokens") or result.get("llm_input_tokens"),
            "output_tokens": row.get("llm_output_tokens") or result.get("llm_output_tokens"),
            "total_tokens": row.get("llm_total_tokens") or result.get("llm_total_tokens"),
            "reasoning_tokens": row.get("llm_reasoning_tokens") or result.get("llm_reasoning_tokens"),
        }
    )
    llm_usage = result.get("llm_usage")
    if isinstance(llm_usage, dict):
        totals = normalize_usage(llm_usage.get("totals"))
        if totals["total_tokens"]:
            usage = totals
    return usage


def usage_parts(row: dict[str, str], result: dict[str, Any]) -> list[UsagePart]:
    trace = role_trace(result)
    llm_usage = result.get("llm_usage")
    parts: list[UsagePart] = []
    if isinstance(llm_usage, dict) and isinstance(llm_usage.get("by_role"), dict):
        for role, raw_usage in llm_usage["by_role"].items():
            usage = normalize_usage(raw_usage)
            if not usage["total_tokens"]:
                continue
            provider, model = role_model(result, trace, str(role))
            cost, pricing_model = calculate_cost(model, usage) if model else (None, None)
            parts.append(UsagePart(provider, model, str(role), usage, cost, pricing_model))
    if parts:
        return parts

    usage = top_level_usage(row, result)
    if not usage["total_tokens"]:
        return []
    provider, model = role_model(result, trace, "planner")
    if not model:
        model = infer_model_from_path(row, result)
        provider = provider_for_model(model, provider)
    cost, pricing_model = calculate_cost(model, usage) if model else (None, None)
    return [UsagePart(provider, model, "all", usage, cost, pricing_model)]


def infer_model_from_path(row: dict[str, str], result: dict[str, Any]) -> str:
    for key in ("planner_model", "reviewer_model", "judge_model", "triage_model"):
        value = str(result.get(key) or row.get(key) or "").strip()
        if value:
            return value
    return ""


def status_bucket(value: str) -> str:
    lowered = (value or "").lower()
    if lowered == "success":
        return "success"
    if lowered == "failure":
        return "failure"
    if lowered:
        return "other"
    return "unknown"


def row_identity(row: dict[str, str], csv_path: Path, row_index: int) -> str:
    result_value = row.get("result_json") or row.get("result_path") or ""
    result_path = resolve_path(result_value, csv_path) if result_value else None
    if result_path:
        return f"result:{result_path}"
    run_id = row.get("run_id") or ""
    if run_id:
        return f"run:{csv_path.parent}:{run_id}"
    return f"csv:{csv_path}:{row_index}"


def collect(dedupe: bool = True) -> dict[str, Any]:
    csv_paths = sorted(OBSERVATIONS_DIR.glob("*/summary.csv"))
    seen: set[str] = set()
    duplicate_rows = 0
    rows: list[dict[str, Any]] = []
    experiments: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    scenarios: dict[str, dict[str, Any]] = {}
    modes: dict[str, dict[str, Any]] = {}
    totals = empty_usage()
    total_cost = 0.0
    unpriced_tokens = 0
    token_rows = 0
    priced_rows = 0
    priced_success_rows = 0

    for csv_path in csv_paths:
        try:
            with csv_path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                csv_rows = list(reader)
        except OSError:
            continue
        experiment_id = csv_path.parent.name
        exp = experiments.setdefault(
            experiment_id,
            {
                "experiment": experiment_id,
                "csv_path": str(csv_path.relative_to(ROOT)),
                "rows": 0,
                "token_rows": 0,
                "priced_rows": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "reasoning_tokens": 0,
                "cost_usd": 0.0,
                "success": 0,
                "failure": 0,
                "other_status": 0,
                "unknown_status": 0,
                "first_started_at": "",
                "last_started_at": "",
                "models": set(),
            },
        )
        for row_index, row in enumerate(csv_rows, start=1):
            identity = row_identity(row, csv_path, row_index)
            if dedupe and identity in seen:
                duplicate_rows += 1
                continue
            seen.add(identity)

            result_value = row.get("result_json") or row.get("result_path") or ""
            result_path = resolve_path(result_value, csv_path) if result_value else None
            result = read_json(result_path) if result_path and result_path.exists() else {}
            parts = usage_parts(row, result)
            usage = empty_usage()
            row_cost = 0.0
            row_priced = False
            row_unpriced_tokens = 0
            part_payloads: list[dict[str, Any]] = []
            for part in parts:
                add_usage(usage, part.usage)
                if part.cost_usd is None:
                    row_unpriced_tokens += part.usage["total_tokens"]
                else:
                    row_cost += part.cost_usd
                    row_priced = True
                model_key = f"{part.provider or 'unknown'}::{part.model or 'unknown'}"
                model_group = models.setdefault(
                    model_key,
                    {
                        "provider": part.provider or "unknown",
                        "model": part.model or "unknown",
                        "pricing_model": part.pricing_model or "",
                        "runs": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "reasoning_tokens": 0,
                        "cost_usd": 0.0,
                        "unpriced_tokens": 0,
                    },
                )
                model_group["runs"] += 1
                model_group["input_tokens"] += part.usage["input_tokens"]
                model_group["output_tokens"] += part.usage["output_tokens"]
                model_group["total_tokens"] += part.usage["total_tokens"]
                model_group["reasoning_tokens"] += part.usage["reasoning_tokens"]
                if part.cost_usd is None:
                    model_group["unpriced_tokens"] += part.usage["total_tokens"]
                else:
                    model_group["cost_usd"] += part.cost_usd
                part_payloads.append(
                    {
                        "role": part.role,
                        "provider": part.provider,
                        "model": part.model,
                        "usage": part.usage,
                        "cost_usd": part.cost_usd,
                        "pricing_model": part.pricing_model,
                    }
                )

            final_status = str(row.get("final_status") or result.get("final_status") or "").strip()
            bucket = status_bucket(final_status)
            scenario = str(row.get("scenario") or result.get("scenario") or "").strip() or "unknown"
            mode = (
                str(row.get("mode") or result.get("execution_mode") or result.get("worker") or row.get("worker") or "")
                .strip()
                or "unknown"
            )
            start = started_at(row, result, csv_path)
            exp["rows"] += 1
            exp[bucket if bucket in ("success", "failure") else f"{bucket}_status"] += 1
            if usage["total_tokens"]:
                token_rows += 1
                exp["token_rows"] += 1
                add_usage(totals, usage)
                exp["input_tokens"] += usage["input_tokens"]
                exp["output_tokens"] += usage["output_tokens"]
                exp["total_tokens"] += usage["total_tokens"]
                exp["reasoning_tokens"] += usage["reasoning_tokens"]
                total_cost += row_cost
                exp["cost_usd"] += row_cost
                unpriced_tokens += row_unpriced_tokens
                if row_priced:
                    priced_rows += 1
                    exp["priced_rows"] += 1
                    if bucket == "success":
                        priced_success_rows += 1
            if start:
                if not exp["first_started_at"] or start < exp["first_started_at"]:
                    exp["first_started_at"] = start
                if not exp["last_started_at"] or start > exp["last_started_at"]:
                    exp["last_started_at"] = start

            model_names = sorted({part.model for part in parts if part.model})
            for model_name in model_names:
                exp["models"].add(model_name)

            for group_map, group_key in ((scenarios, scenario), (modes, mode)):
                group = group_map.setdefault(
                    group_key,
                    {
                        "name": group_key,
                        "runs": 0,
                        "success": 0,
                        "failure": 0,
                        "other_status": 0,
                        "unknown_status": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "cost_usd": 0.0,
                    },
                )
                group["runs"] += 1
                group[bucket if bucket in ("success", "failure") else f"{bucket}_status"] += 1
                group["input_tokens"] += usage["input_tokens"]
                group["output_tokens"] += usage["output_tokens"]
                group["total_tokens"] += usage["total_tokens"]
                group["cost_usd"] += row_cost

            rows.append(
                {
                    "experiment": experiment_id,
                    "csv_path": str(csv_path.relative_to(ROOT)),
                    "row": row_index,
                    "started_at": start,
                    "run_id": row.get("run_id") or "",
                    "scenario": scenario,
                    "mode": mode,
                    "final_status": final_status or "unknown",
                    "elapsed_seconds": to_float(row.get("elapsed_seconds") or result.get("elapsed_seconds")),
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "total_tokens": usage["total_tokens"],
                    "reasoning_tokens": usage["reasoning_tokens"],
                    "cost_usd": row_cost if row_priced else None,
                    "unpriced_tokens": row_unpriced_tokens,
                    "models": model_names,
                    "parts": part_payloads,
                    "result_json": str(result_path.relative_to(ROOT)) if result_path and result_path.exists() else result_value,
                }
            )

    experiments_payload = []
    for exp in experiments.values():
        item = dict(exp)
        item["models"] = sorted(exp["models"])
        experiments_payload.append(item)
    rows.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    experiments_payload.sort(key=lambda item: item["cost_usd"], reverse=True)
    model_payload = sorted(models.values(), key=lambda item: item["cost_usd"], reverse=True)

    return {
        "generated_at": now_iso(),
        "root": str(ROOT),
        "observations_dir": str(OBSERVATIONS_DIR.relative_to(ROOT)),
        "csv_files": len(csv_paths),
        "rows": len(rows),
        "duplicate_rows_skipped": duplicate_rows,
        "dedupe": dedupe,
        "token_rows": token_rows,
        "priced_rows": priced_rows,
        "totals": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "total_tokens": totals["total_tokens"],
            "reasoning_tokens": totals["reasoning_tokens"],
            "cost_usd": total_cost,
            "unpriced_tokens": unpriced_tokens,
            "cost_per_run_usd": total_cost / priced_rows if priced_rows else 0,
            "cost_per_success_usd": total_cost / priced_success_rows if priced_success_rows else 0,
            "priced_success_rows": priced_success_rows,
        },
        "experiments": experiments_payload,
        "models": model_payload,
        "scenarios": sorted(scenarios.values(), key=lambda item: item["cost_usd"], reverse=True),
        "modes": sorted(modes.values(), key=lambda item: item["cost_usd"], reverse=True),
        "runs": rows,
        "pricing": PRICING,
        "notes": [
            "Cost excludes tax, exchange rates, free credits, Batch/Flex/Priority multipliers, regional uplifts, and tool-call fees.",
            "Rows without token columns or usable result JSON remain visible but do not add to token/cost totals.",
            "Unknown models add to unpriced tokens until a matching price entry is added in server.py.",
        ],
    }


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
        target = (STATIC_DIR / path).resolve()
        if not target.is_file() or STATIC_DIR not in target.parents:
            self.send_error(404)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/token-usage":
            query = parse_qs(parsed.query)
            dedupe = query.get("dedupe", ["1"])[0] not in ("0", "false", "False")
            self.send_json(collect(dedupe=dedupe))
            return
        path = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
        target = (STATIC_DIR / path).resolve()
        if not target.is_file() or STATIC_DIR not in target.parents:
            self.send_error(404)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the observations token dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Token dashboard: http://{args.host}:{args.port}")
    print(f"Reading CSV files from: {OBSERVATIONS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
