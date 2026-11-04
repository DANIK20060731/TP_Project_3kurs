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

## 2026-11-04 · харнесс · участник 1 (syab2)
Две проблемы харнесса из журнала T-001:
- **e2e-tester и protect-tests:** в этом режиме теперь можно создавать новые `tests/e2e/test_*.py`. Закоммиченные e2e-спецификации, `conftest.py` и правки через shell по-прежнему заблокированы. Снимать режим перед шагом 5 не нужно.
- **Stop-хук и работа субагентов:** пока в `background_tasks` есть субагент, проверка откладывается и попытки не тратятся. Запущенные shell-задачи её не откладывают.
- **Выход после 3 попыток:** агент получает об этом предупреждение на последней попытке, а человек видит `systemMessage` о красных проверках.

**Осталось:** если координатор завершит ход между отчётом test-writer и коммитом тестов, хук сработает на красных тестах. Поэтому `/task` требует коммитить их в том же ходе; маркер фазы red не вводили, чтобы не создавать способ обойти проверку.

## 2026-11-04 · T-016 · участник 2 (Blokhin Daniil)
- Общий шаблон `templates/base.html`: шапка с `nav` (гость — «Вход»/«Регистрация»; вошедший — «Вы вошли как …», роль, POST «Выйти»), данные только из `request.user`, блок `messages`.
- `static/css/app.css`: свой CSS, mobile-first, переменные в `:root`; в начале файла — перечень классов для следующих задач (`.field`, `.form-narrow`, `.btn-primary/secondary`, `.table-wrap`, `.card`, `.message-*`, `.alert-*`, `.empty`).
- `_form_fields.html` (ошибки в `role="alert"`), оформленные `403.html`/`404.html` на русском.
- Хостинг: статика в prod через WhiteNoise (`CompressedManifestStaticFilesStorage`, новая зависимость согласована); htmx отдаётся локально из `django-htmx` (2.0.10) вместо unpkg.
- `docs/ARCHITECTURE.md`: раздел «Анонимность в views и шаблонах» (messages по `public_code`, без hidden-полей с id, единый 404 для чужого/несуществующего объекта, тест на экран рецензента).
- Ревью: APPROVE, ANONYMITY OK (7 MINOR исправлены). `make check` зелёный (123 теста, 94.35%), `make e2e` 12/12; ручная проверка в браузере 375/1280 px — OK.

**Дальше:** T-002 (курсы) — зависимости T-001, T-016 выполнены. Отдельная задача «Деплой» через `/new-task`: площадка, gunicorn, Postgres, `CSRF_TRUSTED_ORIGINS`, обязательный `collectstatic` (без него manifest-хранилище даёт 500).
**Открыто (minor):** отказ CSRF при `DEBUG=False` показывает стандартную страницу Django, а не наш `403.html` (нужен `403_csrf.html`); `GET /accounts/logout/` → пустой 405. Ссылки шапки собраны через `{% url … as var %}` и молча пропадают при опечатке — каждую новую ссылку покрывать тестом на точный href.
