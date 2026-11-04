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

## 2026-11-04 · T-001 · участник 2 (Blokhin Daniil)
- Кастомный `accounts.User` (`AbstractUser` + `role` student/teacher, по умолчанию student), миграция `accounts/0001_initial`.
- Регистрация без email-подтверждения (решение по открытому вопросу) → сразу вход; вход/выход (`LoginView`/`LogoutView`, выход только POST), общая ошибка входа без раскрытия логина.
- `apps/accounts/permissions.py`: `teacher_required` и `TeacherRequiredMixin` (гость → логин, не преподаватель → 403; `is_staff` роль не даёт). Роль меняет только администратор в админке.
- `seed_demo`: `teacher` — teacher, `student01..30` — student. Фабрики `UserFactory`/`TeacherFactory`.
- ruff isort: `known-first-party = ["apps", "config", "tests"]`.
- Ревью: APPROVE, ANONYMITY OK. `make check` зелёный (66 тестов, покрытие 94.35%), `make e2e` зелёный (5 тестов).

**Дальше:** T-002 (курсы) — можно начинать, зависит от `accounts.User`.
**Открыто (MINOR из ревью):** `seed_demo` перезаписывает роль демо-учёток; `IntegrityError` при одновременной двойной регистрации → 500; вошедший пользователь может открыть signup. Демо-`admin` (superuser, role=student) не записывать на курсы в будущих сид-данных.
**Харнесс:** e2e-tester на шаге 5 не может писать в `tests/e2e/`, т.к. protect-tests снимается только на шаге 6 — тест скопировал человек.
