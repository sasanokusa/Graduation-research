import os
import socket
from contextlib import closing

import pymysql
from fastapi import FastAPI, HTTPException


def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "appuser"),
        password=os.getenv("DB_PASSWORD", "apppassword"),
        database=os.getenv("DB_NAME", "appdb"),
        cursorclass=pymysql.cursors.DictCursor,
    )


app = FastAPI(title="Target API")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def _tcp_probe(host: str, port: int, timeout_seconds: float = 1.0) -> dict:
    try:
        with closing(socket.create_connection((host, port), timeout=timeout_seconds)):
            return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


def _dependency_contract(name: str, *, default_host: str, default_port: int, default_group: str) -> dict:
    prefix = name.upper()
    host = os.getenv(f"{prefix}_HOST", default_host)
    port = int(os.getenv(f"{prefix}_PORT", str(default_port)))
    host_group = os.getenv(f"{prefix}_HOST_GROUP", default_group)
    expected_host = os.getenv(f"{prefix}_EXPECTED_HOST", default_host)
    expected_group = os.getenv(f"{prefix}_EXPECTED_GROUP", default_group)
    probe = _tcp_probe(host, port)
    return {
        "host": host,
        "port": port,
        "host_group": host_group,
        "expected_host": expected_host,
        "expected_group": expected_group,
        "reachable": probe["ok"],
        "expected_host_ok": host == expected_host,
        "expected_group_ok": host_group == expected_group,
        "probe_error": probe["error"],
    }


@app.get("/healthz")
def healthz():
    try:
        with closing(get_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                row = cursor.fetchone()
        return {"status": "ok", "db": row}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"database error: {exc}") from exc


@app.get("/api/items")
def list_items():
    try:
        with closing(get_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, description FROM items ORDER BY id")
                items = cursor.fetchall()
        return {"items": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"database error: {exc}") from exc


@app.get("/api/topology")
def topology_contract():
    dependencies = {
        "cache": _dependency_contract(
            "cache",
            default_host="cache",
            default_port=6379,
            default_group="host-A",
        ),
        "queue": _dependency_contract(
            "queue",
            default_host="queue",
            default_port=6379,
            default_group="host-B",
        ),
        "metrics": _dependency_contract(
            "metrics",
            default_host="metrics",
            default_port=9090,
            default_group="host-B",
        ),
    }
    checks = {
        "dependencies_reachable": all(dep["reachable"] for dep in dependencies.values()),
        "expected_hosts_ok": all(dep["expected_host_ok"] for dep in dependencies.values()),
        "expected_groups_ok": all(dep["expected_group_ok"] for dep in dependencies.values()),
        "degraded_mode_ok": not _env_bool("DEGRADED_MODE"),
    }
    ok = all(checks.values())
    return {
        "status": "ok" if ok else "degraded",
        "app_host_group": os.getenv("APP_HOST_GROUP", "host-A"),
        "checks": checks,
        "dependencies": dependencies,
    }
