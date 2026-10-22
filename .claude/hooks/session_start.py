#!/usr/bin/env python3
"""SessionStart: сразу даёт агенту контекст — ветка, изменения, прогресс, режимы."""

from __future__ import annotations

from _common import PROJECT_DIR, flag, git, ok

parts: list[str] = ["## Контекст сессии (хук SessionStart)"]

branch = git("branch", "--show-current") or "?"
parts.append(f"Ветка: `{branch}`")
if branch in {"main", "master"}:
    parts.append(
        "ВНИМАНИЕ: вы на main. Перед изменениями создайте ветку `feat/T-xxx-slug` "
        "(коммиты в main блокируются хуком)."
    )

status = git("status", "--short")
parts.append("Незакоммиченные изменения:\n" + (status or "(нет)"))
parts.append("Последние коммиты:\n" + (git("log", "--oneline", "-5") or "(нет)"))

progress = PROJECT_DIR / "docs" / "PROGRESS.md"
if progress.exists():
    lines = progress.read_text(encoding="utf-8").strip().splitlines()
    parts.append("Хвост docs/PROGRESS.md:\n" + "\n".join(lines[-25:]))

if flag("protect-tests"):
    parts.append(
        "РЕЖИМ protect-tests: тесты зафиксированы, правка tests/** заблокирована. "
        "Меняйте только код приложения."
    )

ok("\n\n".join(parts))
