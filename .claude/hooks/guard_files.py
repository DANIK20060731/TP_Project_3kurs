#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit): защищённые файлы.

Блокирует:
- секреты: .env* (кроме .env.example);
- применённые миграции: файл миграции, который уже в git, — только новые через makemigrations;
- tests/** в режиме protect-tests (код подгоняется под тесты, а не наоборот). Исключение —
  ещё не закоммиченные tests/e2e/test_*.py: e2e-tester закрепляет ими сценарий на шаге 5 /task.
  Новый тест ничего не ослабляет, а закоммиченные e2e-спецификации остаются защищёнными;
- сам харнесс (.claude/settings.json, .claude/hooks/*) — агент не отключает свои ограничители.
  Человек снимает блок: `touch .claude/.state/harness-unlock`.
"""

from __future__ import annotations

import re

from _common import block, flag, git, ok, read_event, rel

event = read_event()
tool_input = event.get("tool_input") or {}
path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
if not path:
    ok()

p = rel(path)
name = p.rsplit("/", 1)[-1]

if name.startswith(".env") and name != ".env.example":
    block(
        f"Запрещено менять {p}: секреты правит только человек. Добавьте переменную в .env.example."
    )

if re.search(r"(^|/)migrations/\d{4}_.*\.py$", p) and git("ls-files", p):
    block(
        f"{p} — уже закоммиченная миграция, её нельзя редактировать. "
        "Измените модель и выполните `make makemigrations` — будет создана новая миграция."
    )

is_new_e2e_test = re.fullmatch(r"tests/e2e/test_[^/]+\.py", p) and not git("ls-files", p)
if p.startswith("tests/") and flag("protect-tests") and not is_new_e2e_test:
    block(
        f"Режим protect-tests: {p} менять нельзя. Тесты — спецификация задачи. "
        "Исправьте код приложения. Если тест действительно ошибочен — остановитесь "
        "и опишите проблему человеку (или вызовите test-writer через /task). "
        "Исключение — новые файлы tests/e2e/test_*.py (их создаёт e2e-tester)."
    )

if (p == ".claude/settings.json" or p.startswith(".claude/hooks/")) and not flag("harness-unlock"):
    block(
        f"{p} — часть харнесса (ограничители агента). Менять его может только человек: "
        "предложите изменение текстом."
    )

ok()
