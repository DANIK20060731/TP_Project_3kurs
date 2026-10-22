#!/usr/bin/env python3
"""PreToolUse(Bash): не даёт обходить проверки и ломать git-процесс."""

from __future__ import annotations

import re

from _common import block, flag, git, ok, read_event

command: str = (read_event().get("tool_input") or {}).get("command", "")
if not command:
    ok()

RULES: list[tuple[str, str]] = [
    (r"--no-verify\b", "Нельзя пропускать pre-commit хуки (--no-verify). Исправьте ошибки."),
    (r"git\s+push\b.*(--force\b|\s-f\b|--force-with-lease)", "Force-push запрещён."),
    (r"git\s+reset\s+--hard", "git reset --hard уничтожает работу. Используйте git stash."),
    (r"--cov-fail-under[= ]0|--no-cov\b", "Нельзя отключать порог покрытия. Допишите тесты."),
    (r"\bharness-unlock\b", "Разблокировка харнесса — только вручную человеком."),
    (
        r"(cat|less|more|head|tail|source|grep)\s+[^|;&]*\.env(?!\.example)\b",
        "Чтение .env запрещено (секреты).",
    ),
]
for pattern, reason in RULES:
    if re.search(pattern, command):
        block(f"Команда заблокирована хуком guard_bash: {reason}\nКоманда: {command}")

on_main = git("branch", "--show-current") in {"main", "master"}
if re.search(r"\bgit\s+commit\b", command) and on_main:
    block("Коммит в main запрещён. Создайте ветку: git switch -c feat/T-xxx-slug")

if flag("protect-tests") and re.search(
    r"(sed\s+-i|>\s*|tee\s|mv\s|rm\s|cp\s|truncate\s)[^|;&]*\btests/", command
):
    block("Режим protect-tests: изменение tests/** через shell тоже запрещено.")

ok()
