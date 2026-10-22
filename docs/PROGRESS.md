# Журнал прогресса

Агент дописывает запись в конце каждой задачи (шаг 6 `/task`). Хвост этого файла попадает в контекст каждой новой сессии через хук SessionStart.

Формат: `## ГГГГ-ММ-ДД · T-xxx · автор` → что сделано → что дальше / блокеры.

---

## 2026-10-22 · этап 0 · харнесс
- Каркас Django 5.2 (config/settings: base/dev/test/prod), приложение `core` (главная, healthz, `seed_demo`).
- Проверки: ruff, mypy + django-stubs, pytest + hypothesis + factory_boy, coverage ≥ 85%, djlint, pytest-playwright, pip-audit; единая точка входа — Makefile (`make check` = Definition of Done).
- Харнесс Claude Code: CLAUDE.md (+ вложенные для allocation/quality), хуки (SessionStart, guard_files, guard_bash, post_edit, stop_check, notify), 7 субагентов, 8 скиллов, `.mcp.json` (Playwright, Postgres).
- CI GitHub Actions (check на Postgres + e2e), PR-шаблон, pre-commit.
- Документы: SPEC, ARCHITECTURE, GLOSSARY, WORKFLOW, ADR 0001–0003, бэклог T-001…T-015.

**Дальше:** участник 2 — T-001 (кастомный User, до любых других миграций); участник 1 — параллельно T-006 (ядро распределения) и T-011 (детекторы), они не зависят от моделей.
