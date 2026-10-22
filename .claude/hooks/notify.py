#!/usr/bin/env python3
"""Notification: системное уведомление, когда агент ждёт человека."""

from __future__ import annotations

import platform
import subprocess

from _common import ok, read_event

message = (read_event().get("message") or "Claude Code ждёт вашего ответа").replace('"', "'")
if platform.system() == "Darwin":
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "Peer Review · Claude"'],
        check=False,
        capture_output=True,
    )
ok()
