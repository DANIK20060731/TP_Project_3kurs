# Единая точка входа для людей, агента, хуков и CI.
# Definition of Done для любой задачи: `make check` зелёный.

UV      ?= uv
RUN     := $(UV) run
MANAGE  := $(RUN) python manage.py
PYTEST  := $(RUN) pytest

.DEFAULT_GOAL := help
.PHONY: help install up down run migrate makemigrations shell seed \
        format lint types migrations-check test test-fast cov check check-fast \
        e2e security clean

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- окружение
install: ## Поставить зависимости + браузер для e2e + pre-commit
	$(UV) sync
	$(RUN) playwright install chromium
	$(RUN) pre-commit install

up: ## Поднять Postgres/Redis/Mailpit (нужен Docker; без него проект работает на SQLite)
	@command -v docker >/dev/null 2>&1 && docker compose up -d || echo "Docker не найден — используется SQLite (db.sqlite3)"

down: ## Остановить контейнеры
	docker compose down

run: migrate ## Запустить dev-сервер на :8000
	$(MANAGE) runserver 0.0.0.0:8000

migrate: ## Применить миграции
	$(MANAGE) migrate --noinput

makemigrations: ## Создать миграции
	$(MANAGE) makemigrations

shell: ## Django shell
	$(MANAGE) shell

seed: migrate ## Заполнить БД демо-данными
	$(MANAGE) seed_demo

# ---------------------------------------------------------------- проверки
format: ## Отформатировать код
	$(RUN) ruff format .
	$(RUN) ruff check --fix .
	$(RUN) djlint templates apps --reformat --quiet || true

lint: ## ruff + djlint (без исправлений)
	$(RUN) ruff format --check .
	$(RUN) ruff check .
	$(RUN) djlint templates apps --lint

types: ## mypy
	$(RUN) mypy apps config

migrations-check: ## Убедиться, что не забыта миграция
	$(MANAGE) makemigrations --check --dry-run

test: ## Все тесты, кроме e2e
	$(PYTEST) -m "not e2e" -n auto

test-fast: ## Быстрые тесты (без e2e и slow), стоп на первой ошибке
	$(PYTEST) -m "not e2e and not slow" -x -q

cov: ## Тесты + отчёт покрытия (порог в pyproject.toml)
	$(PYTEST) -m "not e2e" -n auto --cov --cov-report=term-missing

check: lint types migrations-check cov ## ПОЛНАЯ проверка = Definition of Done

check-fast: ## Быстрая проверка для хуков агента (~10–20 с)
	@$(RUN) ruff check . --quiet
	@$(RUN) mypy apps config --no-error-summary
	@$(PYTEST) -m "not e2e and not slow" -x -q --no-header

e2e: ## Браузерные тесты (Playwright, поднимают live-сервер сами)
	$(PYTEST) -m e2e

security: ## Аудит зависимостей и настроек
	$(RUN) pip-audit
	$(RUN) ruff check . --select S
	DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=ci-only-$$(date +%s)-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx ALLOWED_HOSTS=example.com $(MANAGE) check --deploy --fail-level WARNING

clean: ## Удалить кэши
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
