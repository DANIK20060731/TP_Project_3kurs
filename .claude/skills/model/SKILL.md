---
name: model
description: Создать Django-модель по шаблону проекта — модель, миграция, admin, фабрика, тесты.
argument-hint: <app>.<Model> <описание полей>
disable-model-invocation: true
---

Создай модель `$ARGUMENTS` по чеклисту:

1. **Модель** в `apps/<app>/models.py`:
   - `verbose_name` у модели и полей (по-русски), `__str__`, `class Meta` с `ordering` и `constraints`. Бизнес-правила — через `CheckConstraint`/`UniqueConstraint`, а не только валидацией в коде;
   - `created_at`/`updated_at` через `apps.core.models.TimeStampedModel` (создай, если его ещё нет);
   - для сущностей, видимых другим студентам, — поле `public_code` (случайный, уникальный) вместо раскрытия id.
2. `make makemigrations` → прочитай миграцию, проверь, что она обратима.
3. **Admin** в `apps/<app>/admin.py`: `list_display`, `list_filter`, `search_fields`, `raw_id_fields` для FK на пользователя.
4. **Фабрика** в `tests/factories.py`.
5. **Тесты** `tests/unit/<app>/test_models.py`: создание через фабрику, `__str__`, каждое ограничение (`IntegrityError`).
6. Обнови раздел «Модель данных» в `docs/ARCHITECTURE.md` (mermaid ER).
7. `make check`.
