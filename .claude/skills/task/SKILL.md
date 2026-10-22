---
name: task
description: Полный цикл выполнения задачи T-xxx — ветка, план, тесты (red), реализация (green), проверки, ревью, e2e, журнал, коммит. Используй, когда человек говорит «сделай задачу T-…» или вызывает /task.
argument-hint: T-xxx
disable-model-invocation: true
---

# /task $ARGUMENTS

Выполни задачу `$ARGUMENTS` строго по шагам. Не пропускай шаги и не объединяй их. После каждого шага кратко отчитайся одной строкой.

## 0. Подготовка
- Найди файл `docs/tasks/$ARGUMENTS-*.md`. Если его нет — остановись и предложи `/new-task`.
- Проверь «Зависимости» в задаче: все зависимые задачи должны иметь статус `done`.
- `git switch main && git pull --ff-only` (если есть remote), затем `git switch -c feat/$ARGUMENTS-<slug>`.
- Поставь в файле задачи `Статус: in-progress`.

## 1. План
Прочитай задачу, связанные разделы `docs/SPEC.md` и `docs/ARCHITECTURE.md`. Составь план: какие файлы, модели, сервисы, views, шаблоны появятся. Если есть «Открытые вопросы» — задай их человеку и дождись ответа.

## 2. Тесты (red)
Вызови субагента **test-writer** с ID задачи. Проверь его отчёт: каждый критерий приёмки покрыт, тесты падают по правильной причине. Затем зафиксируй тесты:
```bash
mkdir -p .claude/.state && touch .claude/.state/protect-tests
git add tests && git commit -m "test($ARGUMENTS): спецификация в тестах (red)"
```

## 3. Реализация (green)
Вызови субагента **implementer**. Цель — `make check` зелёный. Если implementer сообщает, что тест противоречит SPEC, — остановись и спроси человека. Сам режим protect-tests не снимай.

## 4. Ревью
Параллельно вызови **code-reviewer** и **anonymity-auditor** (если задача трогает submissions, reviews, allocation, analytics, notifications или шаблоны). Исправь все BLOCKER/MAJOR/LEAK через implementer. Повтори ревью, пока не будет `APPROVE` и `ANONYMITY OK`.

## 5. E2E
Если в задаче есть раздел «Пользовательский сценарий» — вызови **e2e-tester**. Затем `make e2e`.

## 6. Завершение
- `rm -f .claude/.state/protect-tests`
- `make check` — должен быть зелёным, вывод покажи.
- В файле задачи отметь чекбоксы критериев и поставь `Статус: done`.
- Добавь запись в `docs/PROGRESS.md` (дата, задача, что сделано, что дальше).
- Выполни `/session-log $ARGUMENTS`.
- Закоммить: `feat($ARGUMENTS): <что сделано>` (Conventional Commits).
- Предложи человеку `git push -u origin HEAD` и создание PR по шаблону. Сам не пушь без подтверждения.
