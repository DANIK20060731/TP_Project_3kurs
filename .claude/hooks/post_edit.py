#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit): мгновенная обратная связь по изменённому файлу.

- *.py: ruff format + ruff check --fix; неисправимые ошибки возвращаются агенту;
- models.py: проверка, не нужна ли миграция.
"""

from __future__ import annotations

from _common import PROJECT_DIR, block, find_uv, ok, read_event, rel, run, tail

tool_input = read_event().get("tool_input") or {}
path = tool_input.get("file_path", "")
if not path.endswith(".py"):
    ok()

p = rel(path)
if p.startswith(".claude/") or "/migrations/" in p or not (PROJECT_DIR / p).exists():
    ok()

uv = find_uv()
run([uv, "run", "ruff", "format", "--quiet", p], timeout=60)
lint = run([uv, "run", "ruff", "check", "--fix", "--quiet", p], timeout=60)
problems: list[str] = []
if lint.returncode != 0:
    problems.append(f"ruff нашёл ошибки в {p}:\n{tail(lint.stdout + lint.stderr, 40)}")

if p.endswith("models.py"):
    mig = run([uv, "run", "python", "manage.py", "makemigrations", "--check", "--dry-run"], 120)
    if mig.returncode != 0:
        problems.append(
            "Модели изменились, а миграции нет. Выполните `make makemigrations` "
            f"и проверьте сгенерированный файл.\n{tail(mig.stdout, 15)}"
        )

if problems:
    block("\n\n".join(problems))
ok()
