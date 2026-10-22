---
name: report
description: Написать или обновить раздел пояснительной записки курсовой.
argument-hint: <номер или название раздела>
disable-model-invocation: true
---

Вызови субагента **report-writer** для раздела «$ARGUMENTS».

Перед этим собери актуальные цифры и передай их агенту:
- `make cov` — покрытие;
- `uv run pytest --collect-only -q | tail -1` — число тестов;
- `git log --oneline | wc -l` и `git shortlog -sn` — коммиты и авторы;
- количество файлов в `docs/agent-log/` и `docs/tasks/` со статусом done.

Покажи человеку получившийся раздел и список утверждений, которые стоит перепроверить.
