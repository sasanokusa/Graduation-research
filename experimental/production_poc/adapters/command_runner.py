from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    """Normalized subprocess result without shell execution."""

    args: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    timeout_seconds: int
    duration_ms: int
    exception_class: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CommandRunner(Protocol):
    """Protocol used to make host interactions testable."""

    def run(self, args: list[str], *, timeout_seconds: int) -> CommandResult:
        """Execute a fixed command."""


class SubprocessCommandRunner:
    """Subprocess runner that never uses shell=True."""

    def __init__(self, *, cwd: Path | None = None) -> None:
        self._cwd = cwd

    def run(self, args: list[str], *, timeout_seconds: int) -> CommandResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=timeout_seconds,
                check=False,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            return CommandResult(
                args=args,
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
                timed_out=False,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return CommandResult(
                args=args,
                returncode=None,
                stdout=(exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
                timed_out=True,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                exception_class=exc.__class__.__name__,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            duration_ms = int((time.monotonic() - started) * 1000)
            return CommandResult(
                args=args,
                returncode=None,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                exception_class=exc.__class__.__name__,
            )
