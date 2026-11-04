#!/usr/bin/env python3
"""Stop: агент не может завершить ход с красными проверками.

Если в рабочем дереве есть изменения кода — запускает `make check-fast`.
При ошибке возвращает exit 2: агент получает лог и продолжает чинить.
Предохранитель: после 3 подряд неудачных попыток отпускает агента и
предупреждает человека, что проверки остались красными.

Пока работает субагент, проверка откладывается: координатор ждёт его в фоне, а дерево
недописано, так что красный результат ничего не значит и только тратит попытки. Когда субагент
закончит, координатор проснётся, и при следующей остановке проверка выполнится. Список задач
передаёт сам Claude Code, поэтому агент не может подделать его, чтобы обойти проверку.
"""

from __future__ import annotations

import json
import re
import subprocess

from _common import STATE_DIR, block, find_uv, git, ok, read_event, run, tail

MAX_RETRIES = 3
# Только те, кто пишет код. Забытый dev-сервер (shell) проверку не откладывает.
CODE_WRITING_TASKS = {"subagent", "teammate"}
counter = STATE_DIR / "stop-retries"

event = read_event()
if any(task.get("type") in CODE_WRITING_TASKS for task in event.get("background_tasks") or []):
    ok()

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
    # Отпускаем, чтобы не зациклиться, но человек должен видеть, что задача не готова.
    warning = (
        "Stop-хук отпустил агента с КРАСНЫМИ проверками после "
        f"{MAX_RETRIES} попыток. Задача не готова: запустите `make check`."
    )
    ok(json.dumps({"systemMessage": warning}, ensure_ascii=False))

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
attempts = (
    f"Осталось автоматических попыток: {left}."
    if left > 0
    else "Это последняя попытка: дальше хук вас отпустит, но задача останется не готова. "
    "Если не починили — прямо напишите человеку, что проверки красные, и не говорите «готово»."
)
block(
    "Stop-хук: `make check-fast` упал — задача не готова (Definition of Done).\n"
    f"Исправьте и продолжайте. {attempts} "
    "Если причина вне вашей задачи или тест неверен — прямо скажите об этом человеку.\n\n"
    + tail(result.stdout + "\n" + result.stderr, 80)
)
