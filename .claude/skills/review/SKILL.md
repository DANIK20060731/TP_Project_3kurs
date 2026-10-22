---
name: review
description: Двойное ревью текущих изменений — code-reviewer и anonymity-auditor параллельно, со сводным вердиктом.
disable-model-invocation: true
---

1. Покажи `git diff --stat main...HEAD` и `git status --short`.
2. Запусти **параллельно** субагентов `code-reviewer` и `anonymity-auditor` на текущих изменениях.
3. Сведи результаты в одну таблицу: важность · файл:строка · проблема · кто нашёл.
4. Итог: `APPROVE` только если нет BLOCKER/MAJOR и анонимность OK.
5. Ничего не исправляй сам — спроси человека, исправлять ли (тогда через implementer).
