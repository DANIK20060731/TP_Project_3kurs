"""E2E T-017: авторский стиль «Редакторская правка» в браузере.

Критерии AC-7, AC-8 (вычисленный стиль), AC-12, AC-23 (цвета бейджей), AC-24,
AC-29a (контраст по формуле WCAG 2.x — считается здесь, без новых пакетов),
AC-29b (фокус), AC-29c (prefers-reduced-motion), AC-29d (375 px) и сценарий из
docs/tasks/T-017-visual-style.md без шага главной (он в T-018).
"""

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_base_design_e2e import _assert_header_single_row
from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.unit.core.css_tools import raw_css, root_variables

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

FACTORY_PASSWORD = "pass-12345"  # noqa: S105 — пароль фабрик tests/factories.py
MOBILE = {"width": 375, "height": 740}
DESKTOP = {"width": 1280, "height": 800}
HOME_LINK = re.compile("главн", re.IGNORECASE)
LONG_TITLE = "Лабораторная 1: эхо-сервер"
PHASES = ["submission", "allocation", "review", "closed"]
PHASE_LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}
BROWSER_DEFAULT_LINK = "rgb(0, 0, 238)"


# ---------------------------------------------------------------- данные и вход


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _login(page: Page, live_server, username: str) -> None:
    page.goto(live_server.url + "/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill(FACTORY_PASSWORD)
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(live_server.url + "/")


def _logout(page: Page) -> None:
    page.get_by_role("banner").get_by_role("button", name="Выйти").click()
    expect(page.get_by_text("Вы вошли как")).to_have_count(0)


def _phase_assignment(course, phase: str, title: str):
    now = timezone.now()
    deadlines = {
        "submission": (now + timedelta(days=2), now + timedelta(days=9), None),
        "allocation": (now - timedelta(days=1), now + timedelta(days=6), None),
        "review": (now - timedelta(days=2), now + timedelta(days=5), now - timedelta(days=1)),
        "closed": (now - timedelta(days=9), now - timedelta(days=2), now - timedelta(days=8)),
    }
    submission, review, allocated = deadlines[phase]
    return AssignmentFactory(
        course=course,
        title=title,
        submission_deadline=submission,
        review_deadline=review,
        allocated_at=allocated,
    )


@pytest.fixture
def world():
    """Преподаватель, курс с 2 группами по 5 студентов, группа без студентов, задания 4 фаз."""
    teacher = TeacherFactory(username="teacher")
    course = CourseFactory(owner=teacher, title="Технологии программирования")
    groups = [GroupFactory(course=course, number=n) for n in ("4231", "4232")]
    GroupFactory(course=course, number="4233")
    students = [
        EnrollmentFactory(
            group=groups[i % 2], student=UserFactory(username=f"student{i + 1:02d}")
        ).student
        for i in range(10)
    ]
    assignments = {
        phase: _phase_assignment(course, phase, f"Задание: {PHASE_LABELS[phase]}")
        for phase in PHASES
    }
    long_one = _phase_assignment(course, "submission", LONG_TITLE)
    return {
        "teacher": teacher,
        "course": course,
        "student": students[0],
        "assignments": assignments,
        "long": long_one,
    }


# ---------------------------------------------------------------- цвет и контраст (WCAG 2.x)


def _parse_color(value: str) -> tuple[float, float, float, float]:
    match = re.match(r"rgba?\(([^)]*)\)", value.strip())
    assert match, f"неожиданный формат цвета: {value}"
    parts = [p for p in re.split(r"[\s,/]+", match.group(1)) if p]
    r, g, b = (float(p) for p in parts[:3])
    a = float(parts[3]) if len(parts) > 3 else 1.0
    return r, g, b, a


def _blend(top: tuple[float, float, float, float], bottom: tuple[float, float, float]):
    r, g, b, a = top
    return (r * a + bottom[0] * (1 - a), g * a + bottom[1] * (1 - a), b * a + bottom[2] * (1 - a))


def _effective_bg(chain: list[str]) -> tuple[float, float, float]:
    """Итоговый непрозрачный фон: от корня к элементу, поверх белого холста."""
    bg = (255.0, 255.0, 255.0)
    for value in reversed(chain):
        bg = _blend(_parse_color(value), bg)
    return bg


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_wcag_formula_reference_values():
    """AC-29a: формула теста даёт эталонные значения WCAG (чёрный/белый 21:1, #777/белый ≈ 4.48)."""
    assert round(_contrast((0, 0, 0), (255, 255, 255)), 1) == 21.0
    assert round(_contrast((119, 119, 119), (255, 255, 255)), 2) == 4.48
    assert _effective_bg(["rgba(0, 0, 0, 0)", "rgb(10, 20, 30)"]) == (10.0, 20.0, 30.0)


STYLE_INFO_JS = """
(el) => {
  const cs = getComputedStyle(el);
  const chain = [];
  for (let n = el; n; n = n.parentElement) chain.push(getComputedStyle(n).backgroundColor);
  const r = el.getBoundingClientRect();
  return {
    color: cs.color, chain, size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
    text: (el.innerText || '').trim().slice(0, 40), visible: r.width > 0 && r.height > 0,
  };
}
"""


def _assert_contrast(locator: Locator, what: str, limit: int = 20) -> None:
    count = locator.count()
    assert count > 0, f"на странице нет элементов «{what}»"
    for i in range(min(count, limit)):
        info = locator.nth(i).evaluate(STYLE_INFO_JS)
        if not info["visible"] or not info["text"]:
            continue
        bg = _effective_bg(info["chain"])
        fg = _blend(_parse_color(info["color"]), bg)
        large = info["size"] >= 24 or (info["size"] >= 18.66 and info["weight"] >= 700)
        need = 3.0 if large else 4.5
        ratio = _contrast(fg, bg)
        assert ratio >= need, f"{what} «{info['text']}»: контраст {ratio:.2f} < {need}"


INJECT_MESSAGES_JS = """
() => {
  const main = document.querySelector('main');
  const box = document.createElement('div');
  box.id = 't017-probe';
  const ul = document.createElement('ul');
  ul.className = 'messages';
  for (const kind of ['info', 'success', 'warning', 'error']) {
    const li = document.createElement('li');
    li.className = 'message message-' + kind;
    li.textContent = 'Сообщение ' + kind;
    ul.appendChild(li);
    const alert = document.createElement('div');
    alert.className = 'alert alert-' + kind;
    alert.textContent = 'Предупреждение ' + kind;
    box.appendChild(alert);
  }
  main.prepend(box);
  main.prepend(ul);
}
"""


def test_contrast_guest_pages(page: Page, live_server):
    """AC-29a: гость, 1280 px — текст main, .help, ссылки nav, основная кнопка, сообщения."""
    page.set_viewport_size(DESKTOP)
    page.goto(live_server.url + "/accounts/login/")
    _assert_contrast(page.locator("header nav a"), "ссылка nav")
    _assert_contrast(page.locator("main p, main label"), "текст main")
    _assert_contrast(page.locator("main button[type=submit]"), "основная кнопка")
    page.goto(live_server.url + "/accounts/signup/")
    _assert_contrast(page.locator("main .help"), ".help")
    page.evaluate(INJECT_MESSAGES_JS)
    for kind in ("info", "success", "warning", "error"):
        _assert_contrast(page.locator(f".message-{kind}"), f"message-{kind}")
        _assert_contrast(page.locator(f".alert-{kind}"), f"alert-{kind}")


def test_contrast_student_pages(page: Page, live_server, world):
    """AC-29a: студент — nav (обычная и текущая), бейдж роли, приглушённый текст, таблица, фазы."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, world["student"].username)
    page.goto(live_server.url + "/courses/")
    _assert_contrast(page.locator("header nav a:not([aria-current])"), "ссылка nav")
    _assert_contrast(page.locator('header nav a[aria-current="page"]'), "текущая ссылка nav")
    _assert_contrast(page.locator(".badge-role"), "бейдж роли")
    _assert_contrast(page.locator(".user-name"), "приглушённый текст (имя в шапке)")
    _assert_contrast(page.locator("main th"), "th")
    _assert_contrast(page.locator("main td"), "td")
    _assert_contrast(page.locator("main .btn:not(.btn-secondary)"), ".btn-primary")
    _assert_contrast(page.locator("header .btn-secondary"), ".btn-secondary")
    page.goto(live_server.url + f"/courses/{world['course'].pk}/")
    for phase in PHASES:
        _assert_contrast(page.locator(f".badge-phase--{phase}"), f"бейдж фазы {phase}")


def test_contrast_teacher_pages(page: Page, live_server, world):
    """AC-29a: преподаватель — manage: .help, .empty, th/td, второстепенная кнопка, жетон."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, "teacher")
    page.goto(live_server.url + f"/courses/{world['course'].pk}/manage/")
    _assert_contrast(page.locator("main .help"), ".help")
    _assert_contrast(page.locator("main .empty"), ".empty")
    _assert_contrast(page.locator("main th"), "th")
    _assert_contrast(page.locator("main td"), "td")
    _assert_contrast(page.locator("main .btn-secondary"), ".btn-secondary")
    _assert_contrast(page.locator("main .token"), "жетон кода")
    _assert_contrast(page.locator(".badge-role"), "бейдж роли")
    for phase in PHASES:
        _assert_contrast(page.locator(f"main .badge-phase--{phase}"), f"бейдж фазы {phase}")


# ---------------------------------------------------------------- AC-7, AC-8


PALETTE_JS = """
(names) => names.map((name) => {
  const probe = document.createElement('span');
  probe.style.color = 'var(' + name + ')';
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  return value;
})
"""


def _palette(page: Page) -> set[str]:
    names = [n for n in root_variables(raw_css()) if n.startswith("--color-")]
    assert names
    return set(page.evaluate(PALETTE_JS, names))


def _assert_nav_links_styled(page: Page) -> None:
    links = page.locator("header nav a")
    assert links.count() > 0
    palette = _palette(page)
    for i in range(links.count()):
        link = links.nth(i)
        style = link.evaluate(
            "(el) => ({line: getComputedStyle(el).textDecorationLine,"
            " color: getComputedStyle(el).color})"
        )
        assert style["line"] == "none", f"ссылка nav #{i} подчёркнута: {style}"
        assert style["color"] != BROWSER_DEFAULT_LINK
        assert style["color"] in palette, f"цвет ссылки nav #{i} не из токенов: {style['color']}"


def test_nav_links_not_underlined_and_use_palette(page: Page, live_server, world):
    """AC-7: 1280 px — ссылки nav без подчёркивания, цвет из токена палитры (гость и вошедший)."""
    page.set_viewport_size(DESKTOP)
    page.goto(live_server.url + "/")
    _assert_nav_links_styled(page)
    _login(page, live_server, world["student"].username)
    _assert_nav_links_styled(page)


NAV_STYLE_JS = """
(el) => {
  const cs = getComputedStyle(el);
  return [cs.fontWeight, cs.backgroundColor, cs.borderBottomColor, cs.color];
}
"""


@pytest.mark.parametrize(
    ("who", "url", "current", "other"),
    [
        ("student", "/courses/", "Мои курсы", "Записаться"),
        ("student", "/courses/enroll/", "Записаться", "Мои курсы"),
        ("teacher", "/courses/", "Мои курсы", "Создать курс"),
        ("teacher", "/courses/create/", "Создать курс", "Мои курсы"),
    ],
)
def test_current_nav_link_looks_different(page: Page, live_server, world, who, url, current, other):
    """AC-8: у текущей ссылки aria-current="page", и её стиль отличается от остальных."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, world[who].username)
    page.goto(live_server.url + url)
    nav = page.get_by_role("banner").get_by_role("navigation")
    current_link = nav.get_by_role("link", name=current, exact=True)
    other_link = nav.get_by_role("link", name=other, exact=True)
    expect(current_link).to_have_attribute("aria-current", "page")
    expect(other_link).not_to_have_attribute("aria-current", "page")
    assert current_link.evaluate(NAV_STYLE_JS) != other_link.evaluate(NAV_STYLE_JS), (
        "текущая ссылка nav выглядит как остальные"
    )


# ---------------------------------------------------------------- AC-12


def _assert_in_viewport(locator: Locator, what: str, width: int) -> None:
    expect(locator).to_be_visible()
    box = locator.bounding_box()
    assert box is not None, what
    assert box["x"] >= 0, f"{what} уходит за левый край"
    assert box["x"] + box["width"] <= width, f"{what} не помещается в {width} px"


@pytest.mark.parametrize("who", ["student", "teacher"])
def test_mobile_header_shows_everything_without_menu(page: Page, live_server, who):
    """AC-12: 375 px — знак, имя, бейдж роли, ссылки и «Выйти» видны и в ширине экрана."""
    factory = UserFactory if who == "student" else TeacherFactory
    factory(username=f"very_long_username_{who}_mobile")
    page.set_viewport_size(MOBILE)
    _login(page, live_server, f"very_long_username_{who}_mobile")
    banner = page.get_by_role("banner")
    for url in ("/", "/courses/"):
        page.goto(live_server.url + url)
        _assert_in_viewport(banner.locator('a[href="/"]'), "знак", MOBILE["width"])
        _assert_in_viewport(banner.locator(".user-name"), "имя пользователя", MOBILE["width"])
        _assert_in_viewport(banner.locator(".badge-role"), "бейдж роли", MOBILE["width"])
        links = banner.get_by_role("navigation").get_by_role("link")
        assert links.count() == 2
        for i in range(links.count()):
            _assert_in_viewport(links.nth(i), f"ссылка nav #{i}", MOBILE["width"])
        _assert_in_viewport(banner.get_by_role("button", name="Выйти"), "«Выйти»", MOBILE["width"])


def test_desktop_teacher_header_single_row(page: Page, live_server, world):
    """AC-12: 1280 px — шапка преподавателя с бейджем роли в одну строку на разных страницах."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, "teacher")
    for url in ("/", "/courses/", f"/courses/{world['course'].pk}/manage/"):
        page.goto(live_server.url + url)
        _assert_header_single_row(page)


# ---------------------------------------------------------------- AC-23


def test_phase_badges_differ_visually(page: Page, live_server, world):
    """AC-23: у 4 бейджей фаз разный background-color или border-color, текст есть всегда."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, world["student"].username)
    page.goto(live_server.url + f"/courses/{world['course'].pk}/")
    styles = {}
    for phase in PHASES:
        badge = page.locator(f"main .badge-phase--{phase}").first
        expect(badge).to_have_text(PHASE_LABELS[phase])
        styles[phase] = badge.evaluate(
            "(el) => [getComputedStyle(el).backgroundColor, getComputedStyle(el).borderTopColor]"
        )
    for i, a in enumerate(PHASES):
        for b in PHASES[i + 1 :]:
            assert styles[a] != styles[b], f"бейджи {a} и {b} не различаются: {styles[a]}"


# ---------------------------------------------------------------- AC-24, AC-29d


def _assert_no_horizontal_scroll(page: Page, what: str = "") -> None:
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1], f"{what}: горизонтальная прокрутка scrollWidth/clientWidth={sizes}"


def _assert_form_controls_fit(page: Page, what: str) -> None:
    controls = page.locator(
        "main form input:not([type=hidden]), main form button, main form select, main form textarea"
    )
    for i in range(controls.count()):
        if not controls.nth(i).is_visible():
            continue
        box = controls.nth(i).bounding_box()
        assert box is not None
        assert box["x"] >= 0, f"{what}: элемент формы #{i} уходит за левый край"
        assert box["x"] + box["width"] <= MOBILE["width"], f"{what}: элемент формы #{i} шире экрана"


@pytest.mark.parametrize("who", ["student", "teacher"])
def test_mobile_assignment_list_fits(page: Page, live_server, world, who):
    """AC-24: 375 px — список заданий без прокрутки вбок, фаза и дедлайны в пределах экрана."""
    page.set_viewport_size(MOBILE)
    _login(page, live_server, world[who].username)
    pk = world["course"].pk
    page.goto(
        live_server.url + (f"/courses/{pk}/manage/" if who == "teacher" else f"/courses/{pk}/")
    )
    _assert_no_horizontal_scroll(page, who)
    link = page.get_by_role("main").get_by_role("link", name=LONG_TITLE, exact=True)
    expect(link).to_have_count(1)
    # Локатор для has= ищется внутри контейнера, поэтому без привязки к main.
    title = page.get_by_role("link", name=LONG_TITLE, exact=True)
    table = page.locator("main table", has=title)
    wrap = page.locator("main .table-wrap", has=title)
    container = wrap if wrap.count() else table
    sizes = container.first.evaluate("(el) => [el.scrollWidth, el.clientWidth]")
    assert sizes[0] <= sizes[1], f"список заданий прокручивается вбок: {sizes}"
    row = page.locator("main tr", has=title)
    _assert_in_viewport(row.locator(".badge-phase--submission"), "бейдж фазы", MOBILE["width"])
    times = row.locator("time")
    assert times.count() == 2
    for i in range(2):
        _assert_in_viewport(times.nth(i), f"дедлайн #{i}", MOBILE["width"])


MOBILE_PAGES = [
    ("student", "/", 200),
    ("teacher", "/", 200),
    ("student", "/courses/", 200),
    ("teacher", "/courses/", 200),
    ("student", "/courses/enroll/", 200),
    ("teacher", "/courses/create/", 200),
    ("teacher", "manage", 200),
    ("student", "course", 200),
    ("student", "assignment", 200),
    ("teacher", "assignment", 200),
    ("teacher", "assignment_create", 200),
    ("teacher", "assignment_edit", 200),
    ("student", "manage", 403),
    ("student", "/no-such-page-t017/", 404),
    ("teacher", "group_add", 405),
]


def _mobile_url(world, key: str) -> str:
    pk = world["course"].pk
    apk = world["assignments"]["submission"].pk
    return {
        "manage": f"/courses/{pk}/manage/",
        "course": f"/courses/{pk}/",
        "assignment": f"/assignments/{apk}/",
        "assignment_create": f"/courses/{pk}/assignments/create/",
        "assignment_edit": f"/assignments/{apk}/edit/",
        "group_add": f"/courses/{pk}/groups/add/",
    }.get(key, key)


@pytest.mark.parametrize(("who", "key", "status"), MOBILE_PAGES)
def test_mobile_pages_have_no_horizontal_scroll(page: Page, live_server, world, who, key, status):
    """AC-29d: 375 px — страницы обеих ролей и 403/404/405 без прокрутки вбок, формы в экране."""
    page.set_viewport_size(MOBILE)
    _login(page, live_server, world[who].username)
    response = page.goto(live_server.url + _mobile_url(world, key))
    assert response is not None
    assert response.status == status
    what = f"{who} {key}"
    _assert_no_horizontal_scroll(page, what)
    _assert_form_controls_fit(page, what)


# ---------------------------------------------------------------- AC-29b


FOCUS_JS = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const cs = getComputedStyle(el);
  const chain = [];
  for (let n = el.parentElement; n; n = n.parentElement) {
    chain.push(getComputedStyle(n).backgroundColor);
  }
  return {
    key: el.tagName + '|' + (el.getAttribute('name') || '') + '|' + (el.getAttribute('href') || '')
      + '|' + (el.innerText || el.value || '').trim().slice(0, 30),
    tag: el.tagName.toLowerCase(),
    outlineStyle: cs.outlineStyle, outlineWidth: parseFloat(cs.outlineWidth),
    outlineColor: cs.outlineColor, boxShadow: cs.boxShadow, chain,
  };
}
"""


def _tab_through(page: Page, limit: int = 60) -> list[dict]:
    seen: list[dict] = []
    keys: set[str] = set()
    page.locator("body").evaluate(
        "(el) => { document.activeElement && document.activeElement.blur(); }"
    )
    for _ in range(limit):
        page.keyboard.press("Tab")
        info = page.evaluate(FOCUS_JS)
        if info is None or info["key"] in keys:
            break
        keys.add(info["key"])
        seen.append(info)
    return seen


def _assert_focus_visible(infos: list[dict], what: str) -> None:
    assert infos, f"{what}: клавиша Tab не переводит фокус"
    for info in infos:
        if info["tag"] not in {"a", "button", "input", "select", "textarea"}:
            continue
        bg = _effective_bg(info["chain"])
        outline = info["outlineStyle"] != "none" and info["outlineWidth"] >= 2
        shadow = info["boxShadow"] not in ("", "none")
        assert outline or shadow, f"{what}: нет видимого фокуса у {info['key']}"
        if outline:
            color = info["outlineColor"]
        else:
            match = re.search(r"rgba?\([^)]*\)", info["boxShadow"])
            assert match, f"{what}: не разобрать цвет box-shadow {info['boxShadow']}"
            color = match.group(0)
        ratio = _contrast(_blend(_parse_color(color), bg), bg)
        assert ratio >= 3.0, f"{what}: контраст фокуса {ratio:.2f} < 3 у {info['key']}"


def test_focus_visible_on_login_page(page: Page, live_server):
    """AC-29b: на странице входа у каждой ссылки, поля и кнопки в фокусе видимый индикатор."""
    page.set_viewport_size(DESKTOP)
    page.goto(live_server.url + "/accounts/login/")
    infos = _tab_through(page)
    tags = {i["tag"] for i in infos}
    assert {"a", "input", "button"} <= tags, f"Tab прошёл не по всем элементам: {tags}"
    _assert_focus_visible(infos, "вход")


def test_focus_visible_on_logged_in_home(page: Page, live_server, world):
    """AC-29b: на главной вошедшего фокус виден на ссылках шапки и кнопке «Выйти»."""
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, world["student"].username)
    infos = _tab_through(page)
    assert {"a", "button"} <= {i["tag"] for i in infos}
    _assert_focus_visible(infos, "главная")


# ---------------------------------------------------------------- AC-29c


DURATIONS_JS = """
() => {
  const toSeconds = (v) => v.split(',').map((s) => s.trim()).map(
    (s) => s.endsWith('ms') ? parseFloat(s) / 1000 : parseFloat(s));
  let worst = 0, where = '';
  for (const el of document.querySelectorAll('*')) {
    for (const pseudo of [null, '::before', '::after']) {
      const cs = getComputedStyle(el, pseudo);
      for (const v of [...toSeconds(cs.animationDuration), ...toSeconds(cs.transitionDuration)]) {
        if (v > worst) { worst = v; where = el.tagName + '.' + el.className + (pseudo || ''); }
      }
    }
  }
  return [worst, where];
}
"""


def test_reduced_motion_disables_animations(page: Page, live_server, world):
    """AC-29c: при prefers-reduced-motion длительности анимаций и переходов ≤ 0.01 с."""
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size(DESKTOP)
    for url in ("/", "/accounts/login/"):
        page.goto(live_server.url + url)
        worst, where = page.evaluate(DURATIONS_JS)
        assert worst <= 0.01, f"{url}: длительность {worst} с у {where}"
    _login(page, live_server, world["student"].username)
    for url in ("/", f"/courses/{world['course'].pk}/"):
        page.goto(live_server.url + url)
        worst, where = page.evaluate(DURATIONS_JS)
        assert worst <= 0.01, f"{url}: длительность {worst} с у {where}"


# ---------------------------------------------------------------- сценарий


def test_user_scenario_editorial_style(page: Page, live_server, world, console_errors):
    """Сценарий T-017 (без шага главной — T-018): гость → студент → Tab → преподаватель → 404."""
    home = live_server.url + "/"

    # 1. Гость на 375 px: знак в шапке, без прокрутки вбок → «Вход».
    page.set_viewport_size(MOBILE)
    page.goto(home)
    banner = page.get_by_role("banner")
    expect(banner.get_by_role("link", name=re.compile("Peer Review"))).to_be_visible()
    _assert_no_horizontal_scroll(page, "главная гостя")
    banner.get_by_role("link", name="Вход", exact=True).click()
    expect(page).to_have_url(re.compile(r"/accounts/login/$"))

    # 2. student01 входит: бейдж «Студент», ни одна ссылка не текущая.
    page.get_by_label("Имя пользователя").fill("student01")
    page.get_by_label("Пароль").fill(FACTORY_PASSWORD)
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(home)
    banner = page.get_by_role("banner")
    expect(banner.locator(".badge-role")).to_have_text("Студент")
    expect(banner.locator('[aria-current="page"]')).to_have_count(0)

    # 3. «Мои курсы» подсвечена; курс на 375 px — фаза каждого задания видна без прокрутки.
    banner.get_by_role("link", name="Мои курсы").click()
    expect(page).to_have_url(re.compile(r"/courses/$"))
    expect(page.get_by_role("banner").get_by_role("link", name="Мои курсы")).to_have_attribute(
        "aria-current", "page"
    )
    page.get_by_role("main").get_by_role("link", name="Технологии программирования").click()
    expect(page).to_have_url(re.compile(r"/courses/\d+/$"))
    _assert_no_horizontal_scroll(page, "курс студента")
    badges = page.locator("main [class*='badge-phase--']")
    assert badges.count() == 5
    for i in range(badges.count()):
        _assert_in_viewport(badges.nth(i), f"бейдж фазы #{i}", MOBILE["width"])
    expect(page.get_by_role("banner").get_by_role("link", name="Мои курсы")).to_have_attribute(
        "aria-current", "page"
    )

    # 4. Tab по странице: фокус виден на каждой ссылке и кнопке.
    _assert_focus_visible(_tab_through(page), "курс студента")

    # 5. teacher входит → несуществующий адрес → оформленная 404 → на главную.
    _logout(page)
    _login(page, live_server, "teacher")
    response = page.goto(live_server.url + "/no-such-page-t017/")
    assert response is not None
    assert response.status == 404
    _assert_no_horizontal_scroll(page, "404")
    expect(page.locator("main .error-code")).to_have_text("404")
    expect(page.locator("main .error-code")).to_have_attribute("aria-hidden", "true")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    page.get_by_role("main").get_by_role("link", name=HOME_LINK).click()
    expect(page).to_have_url(home)
    assert [e for e in console_errors if "404" not in e] == []
