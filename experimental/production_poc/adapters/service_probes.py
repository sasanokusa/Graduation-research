from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from experimental.production_poc.adapters.command_runner import CommandRunner


def http_probe(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    """Cheap HTTP GET probe for localhost-oriented health checks."""

    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "body": body[:600],
                "error": "",
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "body": exc.read().decode("utf-8", errors="replace")[:600],
            "error": exc.__class__.__name__,
            "url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "body": str(exc)[:600],
            "error": exc.__class__.__name__,
            "url": url,
        }


def tcp_probe(host: str, port: int, *, timeout_seconds: int) -> dict[str, Any]:
    """TCP reachability probe used for localhost service listeners."""

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return {"ok": True, "host": host, "port": port, "error": ""}
    except Exception as exc:
        return {"ok": False, "host": host, "port": port, "error": exc.__class__.__name__}


def systemd_is_active(runner: CommandRunner, service_name: str, *, timeout_seconds: int) -> dict[str, Any]:
    result = runner.run(["systemctl", "is-active", service_name], timeout_seconds=timeout_seconds)
    state = result.stdout.strip() or result.stderr.strip()
    return {
        "service": service_name,
        "ok": state == "active" and result.returncode == 0,
        "state": state,
        "command": result.args,
        "timed_out": result.timed_out,
    }


def systemd_status_excerpt(runner: CommandRunner, service_name: str, *, timeout_seconds: int) -> dict[str, Any]:
    result = runner.run(
        ["systemctl", "status", service_name, "--no-pager", "--lines=25"],
        timeout_seconds=timeout_seconds,
    )
    return {
        "service": service_name,
        "ok": result.ok,
        "stdout": result.stdout[:1600],
        "stderr": result.stderr[:1600],
        "command": result.args,
    }


def journal_excerpt(
    runner: CommandRunner,
    *,
    service_name: str | None = None,
    lookback_minutes: int,
    lines: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    args = ["journalctl", "--since", f"-{lookback_minutes}m", "--no-pager", "-n", str(lines)]
    if service_name:
        args[1:1] = ["-u", service_name]
    result = runner.run(args, timeout_seconds=timeout_seconds)
    return {
        "service": service_name or "",
        "ok": result.ok,
        "stdout": result.stdout[:2400],
        "stderr": result.stderr[:1200],
        "command": result.args,
    }


def listen_check(runner: CommandRunner, port: int, *, timeout_seconds: int) -> dict[str, Any]:
    result = runner.run(["ss", "-ltnpH"], timeout_seconds=timeout_seconds)
    if not result.ok:
        return {"ok": False, "port": port, "error": result.stderr or "ss failed", "matches": []}
    matches = []
    for line in result.stdout.splitlines():
        local_address = _extract_local_address(line)
        detected_port = _port_from_local_address(local_address)
        if detected_port == port:
            matches.append(line.strip())
    return {"ok": bool(matches), "port": port, "matches": matches, "error": ""}


def tail_log_files(paths: list[Path], *, max_lines: int) -> dict[str, list[str]]:
    """Read last lines from accessible logs without following symlinks or shelling out."""

    excerpts: dict[str, list[str]] = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        excerpts[str(path)] = lines[-max_lines:]
    return excerpts


def count_recent_5xx(log_excerpts: dict[str, list[str]]) -> dict[str, Any]:
    pattern = re.compile(r"\s(5\d{2})\s")
    count = 0
    samples: list[str] = []
    for lines in log_excerpts.values():
        for line in lines:
            if pattern.search(line):
                count += 1
                if len(samples) < 5:
                    samples.append(line[:200])
    return {"count": count, "samples": samples}


def detect_crash_keywords(log_excerpts: dict[str, list[str]], keywords: list[str]) -> dict[str, Any]:
    matches: list[str] = []
    normalized_keywords = [keyword.lower() for keyword in keywords]
    for lines in log_excerpts.values():
        for line in lines:
            lowered = line.lower()
            if any(keyword in lowered for keyword in normalized_keywords):
                matches.append(line[:200])
    return {"count": len(matches), "samples": matches[:5]}


def _extract_local_address(ss_line: str) -> str:
    parts = ss_line.split()
    return parts[3] if len(parts) >= 4 else ""


def _port_from_local_address(local_address: str) -> int | None:
    if not local_address:
        return None
    address = local_address.rsplit(":", 1)
    if len(address) != 2:
        return None
    try:
        return int(address[1])
    except ValueError:
        return None
