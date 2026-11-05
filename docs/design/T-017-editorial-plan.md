# T-017 · План редизайна «Редакторская правка» (направление A)

Документ нужен, чтобы любой участник мог продолжить работу с любого шага. Источник требований — `docs/tasks/T-017-visual-style.md`: критерии AC-*, таблица «На что опираются существующие тесты» и раздел «Решения». Если план расходится с файлом задачи, прав файл задачи.

Ветка: `feat/T-017-visual-style`. Процесс: `/task T-017` (тесты → реализация → `make check` → ревью → e2e → завершение).

## 0. Идея
Интерфейс похож на рукопись у редактора: тёплая бумага, чёрные чернила, красный редакторский карандаш для пометок и текущего. Заголовки набраны антиквой, интерфейс — гротеском, коды и даты — моноширинным. Карточки похожи на листы тетради с красной двойной линией поля слева. Бейджи фаз — контурные «штампы» капителью.

Чего не делаем (анонимность, ARCHITECTURE): аватары, инициалы, цвета или «почерк», выведенные из id или имени пользователя. Метафора пометок на полях не изображает подписи. Работа наружу — только `public_code` в стиле «жетона» (`.token`).

## 1. Рамки T-017 (решения человека 2026-11-05)
- **Входит:** AC-1–AC-12, AC-23–AC-31. Это токены, шапка, кнопки, формы, сообщения, пустые состояния, таблицы, карточки, бейджи фаз, 403/404/405, починка таблицы заданий на 375 px и скриншоты «до/после».
- **Не входит:**
  - главная (AC-13–AC-22) → T-018. Её дизайн описан в §8, чтобы заложить классы;
  - шрифты woff2, `403_csrf.html`, 405 для GET logout → T-019;
  - тёмная тема.
- **Шрифты** только системные.
- **«Мои курсы»** остаются таблицей: e2e T-002 ищет `row`.
- **Тесты не меняем.** В новых ссылках и кнопках не используем подстроки «вход», «регистрация», «мои курсы», «записаться», «создать курс»: Playwright ищет по подстроке.
- **Текущий раздел:** «Мои курсы» подсвечивается на `courses:list`, `courses:detail`, `courses:manage` и всех `assignments:*`. «Записаться» — только на `courses:enroll`, «Создать курс» — только на `courses:create`. На `/` и на страницах ошибок ничего не подсвечивается.
- **Приложения участника 1** (`allocation`, `reviews`, `quality`) не трогаем.

## 2. Дизайн-токены (`:root` в `static/css/app.css`)
Цвета (hex) допустимы **только** в `:root` (AC-2). Контраст посчитан по WCAG 2.x.

| Токен | Значение | Назначение | Контраст |
|---|---|---|---|
| `--color-paper` | `#F7F3EA` | фон `body` | — |
| `--color-surface` | `#FFFDF8` | карточки, поля ввода | — |
| `--color-paper-deep` | `#EFE8DA` | hover строк, `.btn-secondary:hover`, бейдж роли, info | — |
| `--color-ink` | `#1F1B16` | основной текст, основная кнопка, линии | 15.5 / paper, 16.8 / surface, 14.0 / paper-deep |
| `--color-ink-muted` | `#5E564B` | `.help`, мета-строки, `th`, `.empty` | 6.5 / paper, 7.1 / surface, 5.9 / paper-deep |
| `--color-rule` | `#D9D0BF` | тонкие линии таблиц и карточек (декор) | — |
| `--color-field-border` | `#8A7F6E` | рамка полей ввода (не текст, нужно ≥ 3:1) | 3.6 / paper, 3.9 / surface |
| `--color-pencil` | `#A3261C` | акцент: текущий раздел, линия поля, фокус, ошибки, hover основной кнопки | 6.7 / paper, 7.2 / surface |
| `--color-pencil-bg` | `#F8E3DF` | фон ошибок и бейджа «Рецензирование» | pencil на нём 6.0 |
| `--color-green` | `#2F5D50` | успех, бейдж «Сдача работ» | 6.8 / paper |
| `--color-green-bg` | `#E3EDE7` | фон успеха и бейджа сдачи | green на нём 6.3 |
| `--color-ochre` | `#7A4E00` | предупреждения, бейдж «Распределение» | 7.1 / surface |
| `--color-ochre-bg` | `#F6EBCF` | фон предупреждений и бейджа распределения | ochre на нём 6.1 |
| `--color-closed` | `#4A4540` | бейдж «Завершено» | — |
| `--color-closed-bg` | `#E8E3DA` | фон бейджа «Завершено» | closed на нём 7.4 |
| `--color-on-ink` | `#F7F3EA` | текст на основной кнопке (= paper) | 15.5 / ink, 6.7 / pencil (hover) |

Остальные токены:
- **Шрифты:**
  - `--font-serif: Georgia, "PT Serif", "Noto Serif", "DejaVu Serif", "Times New Roman", serif`;
  - `--font-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`;
  - `--font-mono: ui-monospace, "Cascadia Mono", "DejaVu Sans Mono", Menlo, Consolas, monospace`.
- **Кегли:** `--text-sm: .875rem`, `--text-xs: .75rem`, `--text-h1: clamp(1.75rem, 1.2rem + 2vw, 2.5rem)`, `--text-h2: 1.375rem`.
- **Отступы:** `--space-1…--space-12` (0.25/0.5/0.75/1/1.25/1.5/2/2.5/3 rem; имена 1,2,3,4,5,6,8,10,12). Старые `--space-1..6` сохраняют значения.
- **Радиусы:** `--radius-sm: 2px` (кнопки, бейджи, поля), `--radius: 3px` (карточки). Скругления сознательно минимальные: лист бумаги, а не «пилюля».
- **Тени:**
  - `--shadow-sheet: 0 1px 0 var(--color-rule), 0 2px 8px rgba(31, 27, 22, .06)` (литерал rgba внутри `:root` допустим);
  - `--shadow-focus: 0 0 0 3px var(--color-pencil)`.
- **Прочее:** `--content-width: 72rem` (≤ 1200 px, тест T-016), `--duration: 120ms`, `--measure: 68ch` (ширина абзаца).

## 3. База
- `body`: фон paper, шрифт sans, `line-height: 1.55`, цвет ink. `overflow-wrap: break-word` остаётся, `anywhere` не ставить: ломает таблицы (ревью T-016).
- `h1`–`h3`: `--font-serif`, `font-weight: 700`, `letter-spacing: -0.01em`, кегли из токенов. Под `h1` в `main` — тонкая линия-«подчёркивание поля»: `h1::after` — блок 3rem × 2px, цвет pencil. Декор не должен давать текста.
- Ссылки в `main`: цвет ink, `text-decoration-color: var(--color-pencil)`, `text-underline-offset: .2em`, `text-decoration-thickness: 1px`. При hover цвет pencil и толщина 2px. Голубого цвета нигде нет.
- Фокус: `:focus-visible { outline: 3px solid var(--color-pencil); outline-offset: 2px }`. На полях вместо этого рамка pencil плюс `--shadow-focus` (AC-29b: ≥ 2px, контраст с фоном ≥ 3:1).
- `code`, `time`, числа в таблицах: `--font-mono` (только `code`) и `font-variant-numeric: tabular-nums` (`td`, `time`).
- `::selection`: фон pencil-bg, цвет ink.
- `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important } }` (AC-29c).

## 4. Шапка (`templates/base.html`)
Разметка (точные href и тексты ссылок **не меняются**, AC-9/AC-11):
```html
<header class="site-header">
  <div class="site-header__inner">
    <a class="logo wordmark" href="/"><span class="wordmark__mark" aria-hidden="true">¶</span><span class="wordmark__text">Peer Review</span></a>
    <nav class="site-nav" aria-label="Основная навигация">
      <a class="nav-link" href="/courses/" {% if nav_section == "courses" %}aria-current="page"{% endif %}>Мои курсы</a>
      … «Создать курс» (nav_section == "create") / «Записаться» (nav_section == "enroll")
      <span class="user-name">Вы вошли как {{ request.user.username }}</span>
      <span class="badge badge-role user-role">{{ request.user.get_role_display }}</span>
      <form class="logout-form">… <button class="btn btn-secondary btn-sm">Выйти</button></form>
    </nav>
  </div>
</header>
```
- Логотип остаётся ссылкой, а не `h1` (AC-6). Доступное имя — «Peer Review», знак `¶` скрыт `aria-hidden`.
- **`nav_section`** даёт контекст-процессор `apps/core/context_processors.py::nav_section(request)`. Его нужно зарегистрировать в `config/settings/base.py` → `TEMPLATES[0].OPTIONS.context_processors`.
  - Источник — `request.resolver_match` (`namespace`, `url_name`). Если он `None` (страницы 403/404 под тестовым urlconf), отдаём `""`.
  - Правила:
    - `courses:enroll` → `"enroll"`;
    - `courses:create` → `"create"`;
    - прочие `courses:*` и все `assignments:*` → `"courses"`;
    - всё остальное → `""`.
  - Нужен unit-тест на каждое правило. Контекст-процессор не кладёт в контекст ничего о пользователе.
- **CSS шапки:**
  - `.site-header`: фон paper, `border-bottom: 3px double var(--color-ink)`.
  - `__inner`: flex, `flex-wrap: wrap`, `gap`, ширина `--content-width`, по центру.
  - На 1280 px всё в одну строку (тест `_assert_header_single_row`).
  - На 375 px переносы: строка 1 — знак; строка 2 — ссылки, имя, бейдж и «Выйти». Бургера нет, всё видно (AC-12).
- `.wordmark`: `--font-serif`, `font-style: italic`, `font-weight: 700`, `1.375rem`, цвет ink, без подчёркивания. `.wordmark__mark`: цвет pencil, обычное начертание, `margin-right: .15em`.
- `.nav-link`: цвет ink, `text-decoration: none` (AC-7), `padding: .25rem 0`, `border-bottom: 2px solid transparent`. При hover `border-bottom-color: var(--color-rule)`. `[aria-current="page"]`: цвет pencil, `border-bottom-color: var(--color-pencil)`, `font-weight: 600` (AC-8 — отличие по цвету, весу и рамке).
- `.user-name`: `--text-sm`, ink-muted.
- `.badge-role`: см. §6.4, нейтральный вариант (ink на paper-deep, рамка rule).
- `.btn-sm`: компактная кнопка для «Выйти».

## 5. Раскладка
- `main`: `max-width: var(--content-width)`, `margin-inline: auto`, отступы `--space-4` на телефоне и `--space-8` от 40rem. Ширина ≤ 1200 px, отступы слева и справа равны (тест T-016).
- Абзацы описаний: `max-width: var(--measure)`.
- `.page-head` — необязательная обёртка `h1` и мета-строки «Курс: …» на страницах задания и формы. Мета-строка (`.meta`): `--text-sm`, ink-muted.

## 6. Компоненты
### 6.1 Карточка `.card` (лист с линией поля)
- Фон surface, `border: 1px solid var(--color-rule)`, `border-radius: var(--radius)`, `box-shadow: var(--shadow-sheet)`.
- Отступы: `var(--space-5)` и слева `calc(var(--space-5) + var(--space-3))`. `position: relative`.
- `::before`: абсолютная вертикальная линия `top:0; bottom:0; left: var(--space-3); border-left: 3px double var(--color-pencil)` — двойная красная линия поля, как в тетради.
- `h2` внутри: serif, без `::after`.
- Модификаторы:
  - `.card--course` — для главной T-018: название и мета, «растянутая ссылка» `.stretched-link::after { content:""; position:absolute; inset:0 }`. Ссылка содержит только название (AC-26).
  - `.card--plain` — без линии поля, для служебных блоков вроде кода приглашения.
- Вложенные `section.card` не делать: тест manage ищет `section` по группе.

### 6.2 Кнопки
- `.btn`, а также `button[type=submit]` без класса:
  - sans 600, `--text-sm`, `padding: .55rem 1.1rem`, `border: 1px solid var(--color-ink)`, `border-radius: var(--radius-sm)`;
  - фон ink, цвет on-ink, `text-decoration: none`, `transition: background-color var(--duration), border-color var(--duration)`.
- `.btn:hover` — фон и рамка pencil. `.btn:active` — `transform: translateY(1px)`.
- `.btn-primary` — то же, что `.btn`: явный класс для читаемости.
- `.btn-secondary`: фон transparent, цвет ink, рамка ink. При hover фон paper-deep.
- `.btn-sm`: `padding: .3rem .75rem`, `--text-xs`.
- Подписи кнопок **не менять**: «Войти», «Зарегистрироваться», «Создать», «Создать задание», «Сохранить», «Отмена», «Записаться», «Добавить группу», «Перевести», «Изменить», «На главную», «Вернуться к курсу», «Выйти».

### 6.3 Таблицы
- `table`: ширина 100%, `border-collapse: collapse`.
- `th`:
  - `font-variant: small-caps`, `letter-spacing: .06em`, `--text-sm`, цвет ink-muted, `font-weight: 600`;
  - `text-align: left`, `border-bottom: 2px solid var(--color-ink)`.
- `td`: `border-bottom: 1px solid var(--color-rule)`, `padding: var(--space-3) var(--space-2)`, `vertical-align: top`, `tabular-nums`.
- `tbody tr:hover`: фон paper-deep.
- `.table-wrap`: `overflow-x: auto` остаётся для ростера и прочих таблиц.
- **`.table-stack`** чинит AC-24. Это класс на `<table>` списка заданий (`assignments/_course_assignments.html`); разметка одна, без копии для телефона (AC-25). До 40rem:
  - `thead` — визуально скрыт (тот же приём, что `.visually-hidden`);
  - `tr` — `display: block`, лист с рамкой rule и отступом, `margin-bottom: var(--space-3)`;
  - `td` — `display: flex; justify-content: space-between; gap`, без нижней рамки;
  - подпись столбца из `data-label`: `td::before { content: attr(data-label); color: var(--color-ink-muted); font-variant: small-caps }`. Первый `td` (название) — без подписи, жирный, serif.
  - От 40rem — обычная таблица. В шаблоне у каждого `td` атрибут `data-label="Дедлайн сдачи"` и т. д.
  - Обёртку `.table-wrap` у этой таблицы оставить: на телефоне прокрутки уже не будет, `scrollWidth <= clientWidth` (AC-24).
  - Ячейка остаётся внутри `tr`, поэтому `_row_of` в тестах работает.
- Ростер на manage:
  - форма перевода в одну строку: `.inline-form { display:flex; flex-wrap:wrap; align-items:end; gap: var(--space-2) }`;
  - подпись «Перевести в группу» **остаётся видимой**, но мелкая (`--text-xs`, ink-muted);
  - select не тянется на всю ширину: `width:auto; min-width: 6rem`;
  - строки ростера станут примерно в 2 раза ниже (сейчас ~85 px).

### 6.4 Бейджи
- `.badge`:
  - `display:inline-block`, sans 600, `--text-xs`, `text-transform: uppercase`, `letter-spacing: .08em`;
  - `padding: .15rem .5rem`, `border: 1px solid currentColor`, `border-radius: var(--radius-sm)`, `white-space: nowrap`.
- `.badge-phase--submission` — green на green-bg; `--allocation` — ochre на ochre-bg; `--review` — pencil на pencil-bg; `--closed` — closed на closed-bg. Текст фазы всегда есть (AC-23), цвет дополняет текст.
- **Нельзя** давать бейджам `role="status"`: на форме задания тест ждёт ровно один такой элемент.
- `.badge-role`: ink на paper-deep, `border-color: var(--color-rule)`, без uppercase: `font-variant: small-caps`, `letter-spacing: .04em`.
- **Код фазы:** в `apps/courses/services.py` в `AssignmentRow` добавить поле `phase: str` (значение `Phase`, например `"submission"`). Заполнить там же, где `phase_label`. В шаблоне: `<span class="badge badge-phase--{{ assignment.phase }}">{{ assignment.phase_label }}</span>`. На странице задания (`AssignmentDetails.phase` уже есть): `badge-phase--{{ assignment.phase.value }}` (или `{{ assignment.phase }}`, проверить вывод TextChoices). Сопоставлять фазу по русскому тексту в шаблоне нельзя.

### 6.5 Жетон `.token`
- Для `invite_code` сейчас и `public_code` в T-005/T-009:
  - `--font-mono`, `font-weight: 600`, `letter-spacing: .12em`;
  - `padding: .1rem .45rem`, `border: 1px dashed var(--color-ink-muted)`, фон surface.
- Применить к `<code>` кода приглашения на manage и в «Моих курсах» преподавателя. Элемент должен остаться ровно один: `get_by_text` strict.

### 6.6 Формы (`_form_fields.html` — только классы, логику не трогать)
- `.form-narrow`: `max-width: 28rem`.
- `label`: sans 600, `--text-sm`, `margin-bottom: var(--space-1)`.
- `input`/`select`/`textarea`:
  - фон surface, `border: 1px solid var(--color-field-border)`, `border-radius: var(--radius-sm)`;
  - `padding: .55rem .7rem`, `width: 100%`, шрифт inherit.
- `:focus`: `border-color: var(--color-pencil)`, `box-shadow: var(--shadow-focus)`, `outline: none` (индикатор остаётся видимым, AC-29b).
- `.field-invalid` у полей: `border-color: var(--color-pencil)`. `.field-errors`: цвет pencil, `--text-sm`, `::before { content: "✎ " }` — «пометка редактора».
- Селектор полей не должен задевать `input[type=submit]` и чекбоксы (ревью T-016): `input:not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=hidden])`.
- `.field-group` (fieldset форматов): рамка rule, `legend` как `label`. Чекбоксы в 2 колонки от 40rem.
- `.help`: `--text-sm`, ink-muted.
- Вход и регистрация: форма на листе `.card .card--plain .sheet` по центру, ширина `.form-narrow`. Под формой строка «Нет учётной записи? Зарегистрируйтесь»: текст и ссылку не менять.

### 6.7 Сообщения и алерты
- `.message`, `.alert`: фон и левая рамка 4px по виду, `padding: var(--space-3) var(--space-4)`, `border-radius: var(--radius-sm)`, `::before` — глиф:
  - success — green / green-bg, «✓»;
  - warning — ochre / ochre-bg, «!»;
  - error — pencil / pencil-bg, «✎»;
  - info — ink / paper-deep, «¶».
- Глиф декоративный: CSS `content`, в разметке его нет.
- `role` у сообщений не менять (`alert` для error, `status` для прочих).

### 6.8 Пустое состояние `.empty`
- serif italic, ink-muted, `text-align:center`, `border: 1px dashed var(--color-rule)`, фон transparent, `padding: var(--space-6)`. Тексты не менять.

### 6.9 Список «паспорт» `.details` (страница задания)
- Сетка `dt`/`dd` от 40rem, 2 колонки.
- `dt`: small-caps, ink-muted. `dd`: ink, у дат `tabular-nums`.
- Фаза в `dd` — бейдж. **Дата дедлайна видна ровно одним элементом**: не дублировать в «выноске».

### 6.10 Страницы ошибок (403, 404, 405)
- Над `h1` декоративная цифра: `<p class="error-code" aria-hidden="true">404</p>` — serif italic, ~5rem, цвет pencil, `line-height: 1`. Цифры допустимы, английских слов быть не должно (AC-28).
- Текст и единственная ссылка «На главную» (или «Вернуться к курсу» на 405 для владельца) **не меняются**.
- Блок по центру, на листе `.card .card--plain`.

## 7. Изменения по файлам (T-017)
| Файл | Что меняем |
|---|---|
| `static/css/app.css` | Полная перепись по §2–§6. Шапка-комментарий с перечнем классов обновляется (AC-27): `.wordmark`, `.nav-link`, `[aria-current]`, `.badge`, `.badge-role`, `.badge-phase--*`, `.token`, `.table-stack` + `data-label`, `.inline-form`, `.card--course`, `.card--plain`, `.stretched-link`, `.sheet`, `.error-code`, `.meta`, `.btn-sm`. Нет `http(s)://`. |
| `templates/base.html` | Шапка по §4; литералы href не трогать. |
| `apps/core/context_processors.py` (новый) + `config/settings/base.py` | `nav_section`. |
| `apps/courses/services.py` | `AssignmentRow.phase`. |
| `apps/assignments/templates/assignments/_course_assignments.html` | `.table-stack`, `data-label`, бейдж фазы. |
| `apps/assignments/templates/assignments/detail.html` | бейдж фазы в `.details`, мета-строка курса `.meta`. |
| `apps/assignments/templates/assignments/form.html` | мета-строка `.meta` (текст «Курс: …. Фаза: ….» не менять), классы кнопок. |
| `apps/courses/templates/courses/list.html` | `.token` у кода; таблицы остаются; кнопки «Создать курс» и «Записаться на курс» в `main` уже есть и проходят тесты, тексты не менять. |
| `apps/courses/templates/courses/manage.html` | `.card--plain` + `.token` у кода, `.inline-form` в ростере; `section` по группам без вложенных `section`. |
| `apps/courses/templates/courses/detail.html`, `enroll.html`, `create.html` | только классы. |
| `apps/accounts/templates/accounts/login.html`, `signup.html` | обёртка `.sheet`, классы. |
| `templates/403.html`, `404.html`, `405.html` | `.error-code`, `.card--plain`. |
| `templates/_form_fields.html` | только классы, если нужно. |
| `apps/core/templates/core/home.html` | в T-017 не меняется, кроме классов; наполнение — в T-018. |

Не трогать: `apps/allocation`, `apps/reviews`, `apps/quality`, закоммиченные миграции, `tests/**` (protect-tests).

## 8. Задел для T-018 (главная) и будущих экранов
- **Гость:**
  - «титульный лист»: `h1` с «peer-review», лид-абзац;
  - `ol.steps` из 3 `li` с крупными серифными номерами pencil через `counter`: «Сдайте работу до дедлайна» → «Анонимно отрецензируйте работы однокурсников по рубрике» → «Получите рецензии и итоговую оценку»;
  - две кнопки-призыва **без подстрок «вход»/«регистрация»** — «Войти» (`/accounts/login/`) и «Создать учётную запись» (`/accounts/signup/`).
- **Вошедший:** сетка `.card--course` (1 колонка до 40rem, 2–3 от 64rem) и список «Ближайшие дедлайны» `ol.deadlines` (дата моноширинная слева, справа название, курс и бейдж).
  - Пустые состояния: «Ввести код приглашения», «Новый курс».
  - Сервис — dataclass без ORM, правила дедлайнов решаются в T-018.
- **Будущие экраны** (участник 1 и T-005/T-013):
  - работа — `.token` с `public_code`;
  - флаг халтуры — `.badge` pencil с глифом «✎» и комментарием на полях (`.margin-note`: правая колонка от 64rem, на телефоне под текстом);
  - шкала рубрики — ряд контурных «штампов» (радиокнопки, у выбранной заливка ink);
  - конфликт оценок — `.alert-warning` с двумя `.token`.

## 9. Тесты (шаг 2, test-writer)
Распределение по слоям — из «Технических заметок» задачи:
- **unit:** разбор `app.css` — AC-1, AC-2, AC-4 (`url()`), AC-29c (статическая часть); `nav_section` по маршрутам.
- **integration:** AC-3 (нет `style=` и `<style` в исходниках шаблонов), AC-6, AC-8 (`aria-current`), AC-9, AC-10, AC-11, AC-23 (класс бейджа и текст для 4 фаз, на списке и странице задания), AC-25, AC-26, AC-27, AC-28.
- **e2e:** AC-7, AC-8 (стиль отличается), AC-12, AC-24, AC-29a (контраст, формула WCAG в тесте), AC-29b (Tab и фокус), AC-29c (`emulate_media`), AC-29d (375 px на всех экранах), сценарий из задачи без шага главной (он — в T-018).

## 10. Порядок реализации (шаг 3, implementer)
1. Токены и база (§2–§3) — переписать начало `app.css`.
2. Контекст-процессор `nav_section` + шапка (§4).
3. Компоненты: кнопки, формы, сообщения, пустые состояния, таблицы, карточки (§6).
4. `AssignmentRow.phase` + бейджи + `.table-stack` (AC-23, AC-24).
5. Страницы: manage (жетон, ростер), detail задания, вход и регистрация, 403/404/405.
6. Шапка-комментарий `app.css`.
7. `make check`, затем `make e2e`.

## 11. Проверка вручную и скриншоты (шаг 5, AC-31)
- `make seed && make run`. Экраны: главная гостя, главная `teacher`, главная `student01`, «Мои курсы» (обе роли), курс (`teacher` — manage, `student01` — `/courses/1/`), задание `/assignments/1/` (обе роли), вход — на 1280 и 375 px.
- В WSL у Playwright MCP нет Chrome. Снимать скриптом Python Playwright на встроенном Chromium. Снимки «до» сделаны 2026-11-05 и лежат во временной папке сессии; если потерялись — переснять с `main`.
- Снимки прикладываются к PR, в репозиторий не коммитятся.

## 12. Статус
- [x] ST-0, ST-1: контекст, снимки «до», 3 направления. Выбрано **A**.
- [x] Шаг 2: тесты (red).
- [x] Шаг 3: реализация.
- [x] Шаг 4: ревью.
- [x] Шаг 5: e2e, скриншоты.
- [ ] Шаг 6: PROGRESS, журнал, коммит, PR.
