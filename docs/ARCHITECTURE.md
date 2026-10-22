# Архитектура

Монолит на Django 5.2 с серверным рендерингом и HTMX для интерактивности. Обоснование — `adr/0001-django-htmx-monolith.md`.

## Слои
```mermaid
flowchart LR
  B[Браузер<br/>HTML + HTMX] --> V[views<br/>тонкие]
  V --> S[services.py<br/>бизнес-логика, транзакции, права]
  S --> M[(models / PostgreSQL)]
  S --> A[allocation<br/>чистый Python]
  S --> Q[quality.detectors<br/>чистый Python]
  S --> N[notifications<br/>email]
```
- **views**: разбор запроса, проверка роли, вызов сервиса, рендер (полный шаблон или `_partial.html` для HTMX).
- **services**: единственное место, где меняется состояние. Открывают транзакции, проверяют инварианты и дедлайны.
- **Чистые модули** (`allocation`, `quality/detectors`) не импортируют Django — тестируются property-тестами за миллисекунды.

## Приложения и зависимости
```mermaid
flowchart TD
  accounts --> courses --> assignments --> submissions --> reviews
  allocation -.чистый.-> reviews
  quality -.детекторы.-> reviews
  reviews --> analytics
  assignments --> notifications
  reviews --> notifications
```
Правило: зависимости только сверху вниз, циклов нет.

## Модель данных (целевая; уточняется задачами через `/model`)
```mermaid
erDiagram
  User ||--o{ Enrollment : "записан"
  Course ||--o{ Enrollment : ""
  Course ||--o{ Assignment : ""
  Assignment ||--|| Rubric : ""
  Rubric ||--o{ Criterion : ""
  Criterion ||--o{ ScaleLevel : ""
  Assignment ||--o{ Submission : ""
  Submission }o--o{ User : "authors"
  Submission ||--o{ ReviewAssignment : ""
  User ||--o{ ReviewAssignment : "reviewer"
  ReviewAssignment ||--o| Review : ""
  Review ||--o{ CriterionScore : ""
  Review ||--o{ QualityFlag : ""
  Assignment ||--o{ AllocationRun : "seed, параметры"
```
Ключевые поля:
- `Submission.public_code` — случайный код, единственный идентификатор работы, видимый рецензенту.
- `ReviewAssignment(submission, reviewer)` — уникальная пара. Взаимность и самоназначение проверяются сервисом и property-тестами алгоритма.
- `AllocationRun(assignment, seed, k, algorithm, created_at)` — для воспроизводимости.

## Фоновые задачи
Напоминания — management-команда `send_reminders` (идемпотентная, с журналом отправок), запускается по cron или Celery beat. Решение зафиксировать в ADR при реализации T-012.

## Окружения
| | БД | Почта |
|---|---|---|
| dev без Docker | SQLite | консоль |
| dev с `make up` | Postgres 16 | Mailpit :8025 |
| test | SQLite (локально) / Postgres (CI) | locmem |
| CI | Postgres 16 | locmem |
