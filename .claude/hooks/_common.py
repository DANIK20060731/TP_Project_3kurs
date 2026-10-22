"""Общие утилиты хуков Claude Code. Только stdlib — хуки не зависят от venv.

Протокол (https://docs.claude.com/en/docs/claude-code/hooks):
- на stdin приходит JSON события;
- exit 0 — ок (stdout SessionStart попадает в контекст агента);
- exit 2 — блокировка; stderr показывается агенту как причина.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
STATE_DIR = PROJECT_DIR / ".claude" / ".state"


def read_event() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def block(reason: str) -> NoReturn:
    print(reason, file=sys.stderr)
    sys.exit(2)


def ok(message: str = "") -> NoReturn:
    if message:
        print(message)
    sys.exit(0)


def rel(path: str | Path) -> str:
    """Путь относительно корня проекта (в POSIX-виде)."""
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_DIR / p
    try:
        return p.resolve().relative_to(PROJECT_DIR.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def flag(name: str) -> bool:
    """Флаги-маркеры режима работы: .claude/.state/<name>."""
    return (STATE_DIR / name).exists()


def find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv",
        *sorted(home.glob("Library/Python/*/bin/uv")),
        *sorted(home.glob("AppData/Roaming/Python/*/Scripts/uv.exe")),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "uv"


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UV": find_uv()}
    return subprocess.run(
        cmd, cwd=PROJECT_DIR, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )


def git(*args: str) -> str:
    try:
        return run(["git", *args], timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def tail(text: str, lines: int = 60) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])
