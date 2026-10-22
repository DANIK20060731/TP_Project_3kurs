#!/usr/bin/env python3
"""Stop: агент не может завершить ход с красными проверками.

Если в рабочем дереве есть изменения кода — запускает `make check-fast`.
При ошибке возвращает exit 2: агент получает лог и продолжает чинить.
Предохранитель: после 3 подряд неудачных попыток отпускает агента и
просит его честно сообщить человеку, что не так.
"""

from __future__ import annotations

import re
import subprocess

from _common import STATE_DIR, block, find_uv, git, ok, read_event, run, tail

MAX_RETRIES = 3
counter = STATE_DIR / "stop-retries"

event = read_event()
changed = git("status", "--porcelain")
code_changed = any(
    re.search(r"\.(py|html|toml|cfg)$", line) and ".claude/" not in line
    for line in changed.splitlines()
)
if not code_changed:
    counter.unlink(missing_ok=True)
    ok()

retries = int(counter.read_text()) if counter.exists() else 0
if event.get("stop_hook_active") and retries >= MAX_RETRIES:
    counter.unlink(missing_ok=True)
    ok()  # отпускаем, чтобы не зациклиться; агент обязан сообщить о проблеме

try:
    result = run(["make", "check-fast", f"UV={find_uv()}"], timeout=600)
except subprocess.TimeoutExpired:
    block("make check-fast не уложился в 10 минут — найдите зависший тест.")

if result.returncode == 0:
    counter.unlink(missing_ok=True)
    ok()

STATE_DIR.mkdir(parents=True, exist_ok=True)
counter.write_text(str(retries + 1))
left = MAX_RETRIES - retries - 1
block(
    "Stop-хук: `make check-fast` упал — задача не готова (Definition of Done).\n"
    f"Исправьте и продолжайте. Осталось автоматических попыток: {left}. "
    "Если причина вне вашей задачи или тест неверен — прямо скажите об этом человеку.\n\n"
    + tail(result.stdout + "\n" + result.stderr, 80)
)
