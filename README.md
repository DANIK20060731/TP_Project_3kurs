# Peer Review — платформа рецензирования студенческих работ

Курсовая работа по дисциплине «Технологии программирования», ГУАП, 3 курс.

Студенты загружают работы, система анонимно распределяет их на рецензирование по рубрике (без самоназначения и взаимных пар), преподаватель видит статистику, конфликты оценок и «халтурные» рецензии.

Разработка ведётся с помощью кодингового агента Claude Code по описанному процессу — см. [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Быстрый старт
```bash
# 1. uv (если нет): https://docs.astral.sh/uv/  или  pip install --user uv
make install        # зависимости, Chromium для e2e, pre-commit
make check          # полная проверка — должна быть зелёной
make seed && make run   # демо-данные и сервер на http://localhost:8000
```
Docker не обязателен: без него используется SQLite. С Docker — `make up` (Postgres, Redis, Mailpit) и `DATABASE_URL` из `.env.example`.

## Документы
| Файл | Что внутри |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | требования и ключевые сценарии |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | слои, приложения, модель данных |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | процесс разработки с агентом: хуки, субагенты, скиллы, CI |
| [docs/tasks/](docs/tasks/README.md) | бэклог задач с критериями приёмки |
| [docs/PROGRESS.md](docs/PROGRESS.md) | журнал прогресса |
| [CLAUDE.md](CLAUDE.md) | бриф для агента |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | как развернуть проект и подключить своего агента |

## Работа с агентом
```bash
claude              # в корне репозитория
> /task T-006       # полный цикл задачи: тесты → код → проверки → ревью → коммит
```
