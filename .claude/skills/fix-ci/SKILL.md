---
name: fix-ci
description: Разобрать упавший CI текущей ветки и починить.
disable-model-invocation: true
---

1. `gh run list --branch "$(git branch --show-current)" --limit 3`, затем `gh run view <id> --log-failed`. Если `gh` не установлен — попроси человека вставить лог.
2. Определи упавший шаг (lint / types / migrations / tests / coverage / e2e) и воспроизведи локально соответствующей целью `make`.
3. Классифицируй причину:
   - ошибка в коде — исправь;
   - флаки-тест — найди источник недетерминизма (время, порядок, сеть) и устрани его, а не ставь retry;
   - разница окружений (Postgres в CI против SQLite локально) — проверь с `DATABASE_URL` на Postgres, если доступен Docker.
4. `make check`, коммит `fix(ci): …`.
