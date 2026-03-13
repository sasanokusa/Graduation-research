from __future__ import annotations

import hashlib
import os
import socket
import time
from pathlib import Path
from typing import Any

from experimental.production_poc.adapters.backup_provider import BackupProvider
from experimental.production_poc.adapters.command_runner import CommandRunner
from experimental.production_poc.adapters.service_probes import http_probe, tcp_probe
from experimental.production_poc.runtime_prod.config import ProductionPocConfig
from experimental.production_poc.runtime_prod.models import DiscoverySnapshot, compact_context, utc_now_iso


class HostObserver:
    """Collects a conservative host snapshot for later anomaly analysis."""

    def __init__(self, runner: CommandRunner, *, command_timeout_seconds: int = 10) -> None:
        self._runner = runner
        self._command_timeout_seconds = command_timeout_seconds

    def collect_snapshot(
        self,
        config: ProductionPocConfig,
        *,
        backup_provider: BackupProvider,
    ) -> DiscoverySnapshot:
        host = self._collect_host_info()
        services = self._collect_systemd_services()
        processes = self._collect_process_summary()
        ports = self._collect_open_ports()
        disk_usage = self._collect_disk_usage()
        memory_usage = self._collect_memory_usage()
        cpu_usage = self._collect_cpu_usage()
        journal_summary = self._collect_journal_summary(config.monitoring.journal_keywords, config.monitoring.journal_lookback_minutes)
        detected_web = self._detect_web_service(config, services, processes, ports)
        detected_minecraft = self._detect_minecraft(config, services, processes, ports)
        inferred_health_checks = self._infer_health_checks(config, detected_web, detected_minecraft)
        preliminary = DiscoverySnapshot(
            captured_at=utc_now_iso(),
            host=host,
            systemd_services=services,
            process_summary=processes,
            open_ports=ports,
            disk_usage=disk_usage,
            memory_usage=memory_usage,
            cpu_usage=cpu_usage,
            journal_summary=journal_summary,
            detected_web=detected_web,
            detected_minecraft=detected_minecraft,
            inferred_health_checks=inferred_health_checks,
            backup_status=backup_provider.status().to_dict(),
            lightweight_context={},
        )
        return DiscoverySnapshot(
            captured_at=preliminary.captured_at,
            host=preliminary.host,
            systemd_services=preliminary.systemd_services,
            process_summary=preliminary.process_summary,
            open_ports=preliminary.open_ports,
            disk_usage=preliminary.disk_usage,
            memory_usage=preliminary.memory_usage,
            cpu_usage=preliminary.cpu_usage,
            journal_summary=preliminary.journal_summary,
            detected_web=preliminary.detected_web,
            detected_minecraft=preliminary.detected_minecraft,
            inferred_health_checks=preliminary.inferred_health_checks,
            backup_status=preliminary.backup_status,
            lightweight_context=compact_context(preliminary),
        )

    def _collect_host_info(self) -> dict[str, Any]:
        hostname = socket.gethostname()
        uptime_result = self._runner.run(["uptime", "-p"], timeout_seconds=self._command_timeout_seconds)
        uname_result = self._runner.run(["uname", "-srvmo"], timeout_seconds=self._command_timeout_seconds)
        os_release = self._read_os_release()
        return {
            "hostname": hostname,
            "os": os_release,
            "kernel": uname_result.stdout,
            "uptime": uptime_result.stdout or uptime_result.stderr,
        }

    def _collect_systemd_services(self) -> list[dict[str, Any]]:
        result = self._runner.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain", "--no-legend"],
            timeout_seconds=self._command_timeout_seconds,
        )
        services: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            services.append(
                {
                    "unit": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                }
            )
        return services

    def _collect_process_summary(self) -> list[dict[str, Any]]:
        result = self._runner.run(
            ["ps", "-eo", "pid,ppid,comm,%cpu,%mem,args", "--sort=-%cpu", "--no-headers"],
            timeout_seconds=self._command_timeout_seconds,
        )
        processes: list[dict[str, Any]] = []
        for line in result.stdout.splitlines()[:25]:
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            processes.append(
                {
                    "pid": parts[0],
                    "ppid": parts[1],
                    "comm": parts[2],
                    "cpu_percent": parts[3],
                    "memory_percent": parts[4],
                    "args": parts[5][:240],
                }
            )
        return processes

    def _collect_open_ports(self) -> list[dict[str, Any]]:
        result = self._runner.run(["ss", "-ltnpH"], timeout_seconds=self._command_timeout_seconds)
        ports: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 5)
            if len(parts) < 5:
                continue
            local_address = parts[3]
            port = self._port_from_local_address(local_address)
            ports.append(
                {
                    "protocol": "tcp",
                    "local_address": local_address,
                    "port": port,
                    "process": parts[5] if len(parts) > 5 else "",
                }
            )
        return ports

    def _collect_disk_usage(self) -> list[dict[str, Any]]:
        result = self._runner.run(
            ["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"],
            timeout_seconds=self._command_timeout_seconds,
        )
        rows: list[dict[str, Any]] = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            rows.append(
                {
                    "filesystem": parts[0],
                    "used_percent": parts[4],
                    "mountpoint": parts[5],
                }
            )
        return rows

    def _collect_memory_usage(self) -> dict[str, Any]:
        values: dict[str, int] = {}
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                number = raw_value.strip().split()[0]
                if number.isdigit():
                    values[key] = int(number)
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        used = max(total - available, 0)
        used_percent = round((used / total) * 100, 1) if total else 0.0
        return {
            "total_kib": total,
            "available_kib": available,
            "used_kib": used,
            "used_percent": used_percent,
        }

    def _collect_cpu_usage(self) -> dict[str, Any]:
        first = self._read_proc_stat()
        time.sleep(0.1)
        second = self._read_proc_stat()
        idle_delta = second["idle"] - first["idle"]
        total_delta = second["total"] - first["total"]
        used_percent = round((1 - (idle_delta / total_delta)) * 100, 1) if total_delta > 0 else 0.0
        loadavg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return {
            "used_percent": max(0.0, min(used_percent, 100.0)),
            "loadavg_1m": loadavg[0],
            "loadavg_5m": loadavg[1],
            "loadavg_15m": loadavg[2],
        }

    def _collect_journal_summary(self, keywords: list[str], lookback_minutes: int) -> dict[str, Any]:
        result = self._runner.run(
            ["journalctl", "--since", f"-{lookback_minutes}m", "-p", "err..alert", "--no-pager", "-n", "50"],
            timeout_seconds=self._command_timeout_seconds,
        )
        lowered_lines = [line.lower() for line in result.stdout.splitlines()]
        keyword_counts = {keyword: 0 for keyword in keywords}
        for line in lowered_lines:
            for keyword in keywords:
                if keyword.lower() in line:
                    keyword_counts[keyword] += 1
        return {
            "excerpt": result.stdout.splitlines()[-20:],
            "stderr": result.stderr[:400],
            "keyword_counts": keyword_counts,
            "line_hash": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()[:16] if result.stdout else "",
        }

    def _detect_web_service(
        self,
        config: ProductionPocConfig,
        services: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        ports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        explicit_service = config.web.service_name
        selected = None
        detection_method = "unknown"
        if explicit_service:
            selected = explicit_service
            detection_method = "config"
        else:
            active_units = {service["unit"][:-8]: service for service in services if service["unit"].endswith(".service")}
            for candidate in config.web.systemd_candidates:
                if candidate in active_units and active_units[candidate]["active"] == "active":
                    selected = candidate
                    detection_method = "systemd"
                    break
        if not selected:
            for process in processes:
                comm = str(process.get("comm", "")).lower()
                if comm in {"nginx", "apache2", "caddy"}:
                    selected = comm
                    detection_method = "process"
                    break
        listen_ports = [
            port["port"]
            for port in ports
            if port.get("port") in {80, 443, 8080, config.web.port}
        ]
        return {
            "service_name": selected or "",
            "server_type": selected or "unknown",
            "detection_method": detection_method,
            "listen_ports": sorted({port for port in listen_ports if isinstance(port, int)}),
            "active": bool(selected),
        }

    def _detect_minecraft(
        self,
        config: ProductionPocConfig,
        services: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        ports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        explicit_service = config.minecraft.service_name
        if explicit_service:
            return {
                "service_name": explicit_service,
                "launch_method": "config",
                "port": config.minecraft.port,
                "active": True,
            }

        for service in services:
            unit_name = service.get("unit", "")
            if "minecraft" in unit_name.lower():
                return {
                    "service_name": unit_name[:-8] if unit_name.endswith(".service") else unit_name,
                    "launch_method": "systemd",
                    "port": config.minecraft.port,
                    "active": service.get("active") == "active",
                }

        screen_result = self._runner.run(["screen", "-ls"], timeout_seconds=2)
        if "minecraft" in screen_result.stdout.lower():
            return {
                "service_name": "",
                "launch_method": "screen",
                "port": config.minecraft.port,
                "active": True,
            }

        tmux_result = self._runner.run(["tmux", "ls"], timeout_seconds=2)
        if "minecraft" in tmux_result.stdout.lower():
            return {
                "service_name": "",
                "launch_method": "tmux",
                "port": config.minecraft.port,
                "active": True,
            }

        for process in processes:
            args = str(process.get("args", "")).lower()
            if "java" in args and any(hint in args for hint in config.minecraft.process_hints):
                launch_method = "shell_script" if ".sh" in args else "java_process"
                detected_port = config.minecraft.port
                for port_row in ports:
                    if port_row.get("port") == config.minecraft.port:
                        detected_port = config.minecraft.port
                        break
                return {
                    "service_name": "",
                    "launch_method": launch_method,
                    "port": detected_port,
                    "active": True,
                }

        return {
            "service_name": "",
            "launch_method": "unknown",
            "port": config.minecraft.port,
            "active": False,
        }

    def _infer_health_checks(
        self,
        config: ProductionPocConfig,
        detected_web: dict[str, Any],
        detected_minecraft: dict[str, Any],
    ) -> dict[str, Any]:
        selected_web = ""
        web_probe_result: dict[str, Any] = {"ok": False, "status": None}
        for url in config.web.health_urls:
            probe = http_probe(url, timeout_seconds=2)
            if selected_web == "":
                selected_web = url
                web_probe_result = probe
            if probe.get("ok"):
                selected_web = url
                web_probe_result = probe
                break
        minecraft_probe = tcp_probe(
            config.minecraft.tcp_host,
            int(detected_minecraft.get("port") or config.minecraft.port),
            timeout_seconds=2,
        )
        return {
            "web": {
                "kind": "http",
                "selected_target": selected_web,
                "probe_result": web_probe_result,
                "service_name": detected_web.get("service_name", ""),
            },
            "minecraft": {
                "kind": "tcp",
                "selected_target": f"{config.minecraft.tcp_host}:{detected_minecraft.get('port') or config.minecraft.port}",
                "probe_result": minecraft_probe,
                "service_name": detected_minecraft.get("service_name", ""),
            },
        }

    @staticmethod
    def _read_os_release() -> dict[str, str]:
        path = Path("/etc/os-release")
        values: dict[str, str] = {}
        if not path.exists():
            return values
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            values[key] = raw_value.strip().strip('"')
        return values

    @staticmethod
    def _read_proc_stat() -> dict[str, int]:
        path = Path("/proc/stat")
        if not path.exists():
            return {"idle": 0, "total": 0}
        fields = path.read_text(encoding="utf-8", errors="replace").splitlines()[0].split()[1:]
        values = [int(field) for field in fields]
        idle = values[3] + values[4]
        total = sum(values)
        return {"idle": idle, "total": total}

    @staticmethod
    def _port_from_local_address(local_address: str) -> int | None:
        parts = local_address.rsplit(":", 1)
        if len(parts) != 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None
