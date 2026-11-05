"""T-017: авторский стиль — разметка шапки, бейджей, жетонов и страниц ошибок.

Критерии AC-3, AC-4, AC-6, AC-8–AC-11, AC-23, AC-25–AC-28 из
docs/tasks/T-017-visual-style.md (рамки — раздел «Решения»; главная — T-018).
Проверяются разметка и ключевые классы; вычисленные стили — в e2e.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.conf import settings
from freezegun import freeze_time

from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.core.html_tree import Element, parse

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
HOME_LINK = re.compile("главн", re.IGNORECASE)
PHASE_LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}
PHASE_DEADLINES = {
    "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
    "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
    "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
    "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
}
ENGLISH_LEAKS = (
    "Forbidden",
    "Not Found",
    "Method Not Allowed",
    "Traceback",
    "Http404",
    "PermissionDenied",
    "URLconf",
)


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def world():
    """Владелец, его курс с группой и заданием, записанный студент."""
    owner = TeacherFactory(username="prof_style")
    course = CourseFactory(owner=owner, title="Технологии программирования")
    group = GroupFactory(course=course, number="4231")
    student = EnrollmentFactory(group=group, student=UserFactory(username="stud_style")).student
    assignment = AssignmentFactory(course=course, title="Лабораторная 1: эхо-сервер")
    return {"owner": owner, "course": course, "student": student, "assignment": assignment}


# ---------------------------------------------------------------- helpers


def _classes(el: Element) -> list[str]:
    return el.attrs.get("class", "").split()


def _header(response) -> Element:
    header = parse(response.content).find("header")
    assert header is not None, "в странице нет <header>"
    return header


def _main(response) -> Element:
    main = parse(response.content).find("main")
    assert main is not None, "в странице нет <main>"
    return main


def _links(el: Element, text: str) -> list[Element]:
    return [a for a in el.find_all("a") if a.text == text]


def _by_class(el: Element, cls: str) -> list[Element]:
    return [e for e in el.iter() if cls in _classes(e)]


def _assignment_in_phase(course, phase: str, title: str):
    submission, review, allocated = PHASE_DEADLINES[phase]
    return AssignmentFactory(
        course=course,
        title=title,
        submission_deadline=submission,
        review_deadline=review,
        allocated_at=allocated,
    )


def _row_of(response, title: str) -> Element:
    """Как ``_row_of`` в assignments/test_course_pages: ближайший tr/li/article/section."""
    found = _links(_main(response), title)
    assert len(found) == 1, f"ожидалась одна ссылка «{title}», есть {len(found)}"
    node = found[0]
    while node is not None and node.tag not in {"tr", "li", "article", "section"}:
        node = node.parent
    assert node is not None, f"ссылка «{title}» не внутри строки списка"
    return node


def _template_files() -> list[Path]:
    base = Path(settings.BASE_DIR)
    files = sorted((base / "templates").rglob("*.html"))
    files += sorted(base.glob("apps/*/templates/**/*.html"))
    return files


# ---------------------------------------------------------------- AC-3


def test_template_sources_found():
    """AC-3: перечень шаблонов не пуст (тест ниже действительно что-то проверяет)."""
    names = {p.name for p in _template_files()}
    assert {"base.html", "404.html", "home.html", "manage.html", "detail.html"} <= names


@pytest.mark.parametrize(
    "path",
    _template_files(),
    ids=lambda p: str(p.relative_to(Path(settings.BASE_DIR))),
)
def test_template_sources_have_no_inline_styles(path):
    """AC-3: в исходниках шаблонов нет style= и <style (не только в BASE_PAGES)."""
    source = path.read_text(encoding="utf-8")
    assert "style=" not in source
    assert "<style" not in source


# ---------------------------------------------------------------- AC-4


def _is_local(url: str) -> bool:
    return not url.startswith("//") and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url)


def _pages_for_ac4(client, world) -> list[tuple[str, bytes]]:
    pages = [
        ("/", client.get("/").content),
        ("/accounts/login/", client.get("/accounts/login/").content),
    ]
    client.force_login(world["student"])
    for url in (
        "/",
        "/courses/",
        f"/courses/{world['course'].pk}/",
        f"/assignments/{world['assignment'].pk}/",
    ):
        pages.append((f"student {url}", client.get(url).content))
    client.force_login(world["owner"])
    for url in ("/", f"/courses/{world['course'].pk}/manage/"):
        pages.append((f"teacher {url}", client.get(url).content))
    return pages


def test_rendered_pages_load_only_local_assets(client, world):
    """AC-4: href у <link>, src у <script> и <img> — локальные; стили — из /static/."""
    for name, html in _pages_for_ac4(client, world):
        tree = parse(html)
        urls = [el.attrs.get("href", "") for el in tree.find_all("link")]
        urls += [el.attrs.get("src", "") for el in tree.find_all("script") if el.attrs.get("src")]
        urls += [el.attrs.get("src", "") for el in tree.find_all("img")]
        bad = [u for u in urls if not _is_local(u)]
        assert bad == [], f"{name}: внешние адреса {bad}"
        sheets = [el.attrs.get("href", "") for el in tree.find_all("link", rel="stylesheet")]
        assert sheets, f"{name}: нет стилей"
        assert all(href.startswith("/static/") for href in sheets), f"{name}: {sheets}"


# ---------------------------------------------------------------- AC-6


def _wordmark(response) -> Element:
    header = _header(response)
    marks = [a for a in header.find_all("a") if a.attrs.get("href") == "/"]
    assert len(marks) == 1, f"в шапке ожидалась одна ссылка href='/', есть {len(marks)}"
    return marks[0]


def _accessible_name(el: Element) -> str:
    """Текст без детей с aria-hidden="true" плюс alt у <img>; aria-label — приоритетнее."""
    if el.attrs.get("aria-label"):
        return el.attrs["aria-label"]
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.attrs.get("aria-hidden") == "true":
            continue
        elif child.tag == "img":
            parts.append(child.attrs.get("alt", ""))
        else:
            parts.append(_accessible_name(child))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


@pytest.mark.parametrize("who", ["guest", "student", "owner"])
def test_header_wordmark_is_home_link_named_peer_review(client, world, who):
    """AC-6: словесный знак — ссылка на /, доступное имя с «Peer Review», не h1, без style=."""
    if who != "guest":
        client.force_login(world[who])
    for url in ("/", "/courses/") if who != "guest" else ("/", "/accounts/login/"):
        mark = _wordmark(client.get(url))
        assert "Peer Review" in _accessible_name(mark)
        assert mark.tag == "a"
        assert mark.find_all("h1") == []
        for el in [mark, *mark.iter()]:
            assert "style" not in el.attrs
            if el.tag == "img":
                assert el.attrs.get("alt", "").strip(), "у <img> знака пустой alt"


# ---------------------------------------------------------------- AC-8, AC-9


def _current_links(response) -> list[Element]:
    header = _header(response)
    return [el for el in header.iter() if el.attrs.get("aria-current") is not None]


def _assert_current(response, expected: str | None) -> None:
    current = _current_links(response)
    if expected is None:
        assert current == [], f"подсвечен раздел: {[a.text for a in current]}"
        return
    assert len(current) == 1, f"ожидалась одна текущая ссылка, есть {[a.text for a in current]}"
    link = current[0]
    assert link.tag == "a"
    assert link.attrs.get("aria-current") == "page"
    # AC-9: текст ссылки прежний, без скрытых добавок.
    assert link.text == expected
    nav = _header(response).find("nav")
    assert nav is not None
    assert link in nav.find_all("a"), "текущая ссылка — не в nav шапки"


STUDENT_CASES = [
    ("/courses/", "Мои курсы"),
    ("/courses/enroll/", "Записаться"),
    ("/", None),
    ("course_detail", "Мои курсы"),
    ("assignment_detail", "Мои курсы"),
]
TEACHER_CASES = [
    ("/courses/", "Мои курсы"),
    ("/courses/create/", "Создать курс"),
    ("/", None),
    ("course_manage", "Мои курсы"),
    ("assignment_detail", "Мои курсы"),
    ("assignment_edit", "Мои курсы"),
    ("assignment_create", "Мои курсы"),
]


def _url(world, key: str) -> str:
    course, assignment = world["course"], world["assignment"]
    return {
        "course_detail": f"/courses/{course.pk}/",
        "course_manage": f"/courses/{course.pk}/manage/",
        "assignment_detail": f"/assignments/{assignment.pk}/",
        "assignment_edit": f"/assignments/{assignment.pk}/edit/",
        "assignment_create": f"/courses/{course.pk}/assignments/create/",
    }.get(key, key)


@pytest.mark.parametrize(("key", "expected"), STUDENT_CASES)
def test_student_current_section_has_aria_current(client, world, key, expected):
    """AC-8/AC-9: у студента текущий раздел — aria-current="page", текст ссылки прежний."""
    client.force_login(world["student"])
    response = client.get(_url(world, key))
    assert response.status_code == 200
    _assert_current(response, expected)


@pytest.mark.parametrize(("key", "expected"), TEACHER_CASES)
def test_teacher_current_section_has_aria_current(client, world, key, expected):
    """AC-8/AC-9: у преподавателя «Мои курсы» на курсах и заданиях, «Создать курс» — на create."""
    client.force_login(world["owner"])
    response = client.get(_url(world, key))
    assert response.status_code == 200
    _assert_current(response, expected)


def test_guest_header_has_no_current_section(client):
    """AC-8: у гостя ни одна ссылка шапки не помечена текущей."""
    for url in ("/", "/accounts/login/", "/accounts/signup/"):
        _assert_current(client.get(url), None)


# ---------------------------------------------------------------- AC-10


@pytest.mark.parametrize(("who", "label"), [("student", "Студент"), ("owner", "Преподаватель")])
def test_role_is_single_badge_in_header(client, world, who, label):
    """AC-10: роль — ровно один .badge-role в шапке; «Вы вошли как» — один раз, в шапке."""
    user = world[who]
    client.force_login(user)
    for url in ("/", "/courses/", "/no-such-page/"):
        response = client.get(url)
        tree = parse(response.content)
        badges = _by_class(tree, "badge-role")
        assert len(badges) == 1, f"{url}: бейджей роли {len(badges)}"
        assert badges[0].text == label
        assert badges[0] in _header(response).iter()
        html = response.content.decode()
        assert html.count("Вы вошли как") == 1
        assert f"Вы вошли как {user.username}" in _header(response).text


# ---------------------------------------------------------------- AC-11


def _header_hrefs(response) -> dict[str, str]:
    """Ссылки шапки: «знак» для href="/", иначе текст → href."""
    result: dict[str, str] = {}
    for a in _header(response).find_all("a"):
        key = "знак" if a.attrs.get("href") == "/" else a.text
        assert key not in result, f"в шапке две ссылки «{key}»"
        result[key] = a.attrs.get("href", "")
    return result


def test_guest_header_links_have_exact_hrefs(client):
    """AC-11: у гостя в шапке ровно знак, «Вход» и «Регистрация» с точными href."""
    assert _header_hrefs(client.get("/")) == {
        "знак": "/",
        "Вход": "/accounts/login/",
        "Регистрация": "/accounts/signup/",
    }


def test_student_header_links_have_exact_hrefs(client, world):
    """AC-11: у студента — знак, «Мои курсы», «Записаться»; новых ссылок без теста нет."""
    client.force_login(world["student"])
    for url in ("/", "/courses/enroll/"):
        assert _header_hrefs(client.get(url)) == {
            "знак": "/",
            "Мои курсы": "/courses/",
            "Записаться": "/courses/enroll/",
        }


def test_teacher_header_links_have_exact_hrefs(client, world):
    """AC-11: у преподавателя — знак, «Мои курсы», «Создать курс»."""
    client.force_login(world["owner"])
    for url in ("/", "/courses/create/"):
        assert _header_hrefs(client.get(url)) == {
            "знак": "/",
            "Мои курсы": "/courses/",
            "Создать курс": "/courses/create/",
        }


# ---------------------------------------------------------------- AC-23


def _assert_phase_badge(container: Element, phase: str) -> None:
    badges = _by_class(container, f"badge-phase--{phase}")
    assert len(badges) == 1, f"бейджей фазы {phase}: {len(badges)}"
    badge = badges[0]
    assert "badge" in _classes(badge)
    assert badge.text == PHASE_LABELS[phase]
    # На форме задания тест ждёт ровно один role="status": бейджам его не даём.
    assert badge.attrs.get("role") is None
    others = [p for p in PHASE_LABELS if p != phase]
    assert not [c for c in _classes(badge) if c in {f"badge-phase--{o}" for o in others}]


@pytest.fixture
def phased(world):
    course = world["course"]
    return {phase: _assignment_in_phase(course, phase, f"Фаза-{phase}") for phase in PHASE_LABELS}


@pytest.mark.parametrize("phase", list(PHASE_LABELS))
def test_student_course_page_shows_phase_badge(client, world, phased, phase):
    """AC-23: на странице курса студента фаза — бейдж с модификатором и русским текстом."""
    client.force_login(world["student"])
    response = client.get(f"/courses/{world['course'].pk}/")
    _assert_phase_badge(_row_of(response, f"Фаза-{phase}"), phase)


@pytest.mark.parametrize("phase", list(PHASE_LABELS))
def test_manage_assignments_show_phase_badge(client, world, phased, phase):
    """AC-23: в разделе «Задания» на manage фаза — бейдж с модификатором."""
    client.force_login(world["owner"])
    response = client.get(f"/courses/{world['course'].pk}/manage/")
    _assert_phase_badge(_row_of(response, f"Фаза-{phase}"), phase)


@pytest.mark.parametrize("who", ["student", "owner"])
@pytest.mark.parametrize("phase", list(PHASE_LABELS))
def test_assignment_page_shows_phase_badge(client, world, phased, phase, who):
    """AC-23: на странице задания фаза — бейдж с модификатором (обе роли)."""
    client.force_login(world[who])
    response = client.get(f"/assignments/{phased[phase].pk}/")
    assert response.status_code == 200
    _assert_phase_badge(_main(response), phase)


# ---------------------------------------------------------------- AC-25


def _assignments_table(response, title: str) -> Element:
    node = _row_of(response, title)
    while node is not None and node.tag != "table":
        node = node.parent
    assert node is not None, "список заданий — не таблица"
    return node


@pytest.mark.parametrize("who", ["student", "owner"])
def test_assignment_list_is_single_stacked_table(client, world, who):
    """AC-25/AC-24: одна разметка списка — таблица .table-stack с data-label у ячеек."""
    other = AssignmentFactory(
        course=world["course"],
        title="Лабораторная 2",
        submission_deadline=datetime(2030, 3, 10, 20, 30, tzinfo=UTC),
        review_deadline=datetime(2030, 3, 17, 18, 15, tzinfo=UTC),
    )
    client.force_login(world[who])
    url = f"/courses/{world['course'].pk}/" + ("manage/" if who == "owner" else "")
    response = client.get(url)
    table = _assignments_table(response, other.title)
    assert "table-stack" in _classes(table)
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        assert len(cells) >= 4
        for td in cells[1:]:
            assert td.attrs.get("data-label", "").strip(), f"нет data-label у ячейки «{td.text}»"
    main = _main(response)
    # Ровно одна ссылка на каждое задание и одна копия дедлайнов — без «мобильного» дубля.
    for title in (world["assignment"].title, other.title):
        assert len(_links(main, title)) == 1
    assert main.text.count("10.03.2030 23:30") == 1
    assert main.text.count("17.03.2030 21:15") == 1


# ---------------------------------------------------------------- AC-26


BLOCK_TAGS = {"section", "article", "div", "table", "ul", "ol", "li", "p", "h1", "h2", "h3"}


@pytest.mark.parametrize("who", ["student", "owner"])
def test_cards_are_not_wrapped_in_links(client, world, who):
    """AC-26: карточки не обёрнуты в <a>; ссылка-название содержит только название."""
    client.force_login(world[who])
    pk = world["course"].pk
    urls = ["/courses/", f"/assignments/{world['assignment'].pk}/"]
    urls.append(f"/courses/{pk}/manage/" if who == "owner" else f"/courses/{pk}/")
    for url in urls:
        main = _main(client.get(url))
        for a in main.find_all("a"):
            assert not [el for el in a.iter() if el.tag in BLOCK_TAGS], (
                f"{url}: ссылка «{a.text}» оборачивает блок"
            )


def test_assignment_details_and_manage_sections_are_cards(client, world):
    """AC-26: «паспорт» задания и секции manage — общий класс .card."""
    client.force_login(world["owner"])
    main = _main(client.get(f"/assignments/{world['assignment'].pk}/"))
    details = main.find("dl")
    assert details is not None
    node = details
    while node is not None and "card" not in _classes(node):
        node = node.parent
    assert node is not None, "список параметров задания — не внутри .card"
    manage = _main(client.get(f"/courses/{world['course'].pk}/manage/"))
    sections = manage.find_all("section")
    assert sections
    assert all("card" in _classes(s) for s in sections)


# ---------------------------------------------------------------- AC-27


@pytest.mark.parametrize("where", ["list", "manage"])
def test_invite_code_is_single_token(client, world, where):
    """AC-27 (план §6.5): код приглашения — ровно один моноширинный жетон .token."""
    client.force_login(world["owner"])
    url = "/courses/" if where == "list" else f"/courses/{world['course'].pk}/manage/"
    main = _main(client.get(url))
    code = world["course"].invite_code
    tokens = _by_class(main, "token")
    assert [t.text for t in tokens] == [code]
    assert main.text.count(code) == 1, "код приглашения выведен не одним элементом"


def test_student_pages_have_no_token_with_invite_code(client, world):
    """AC-27 (анонимность): студенту код приглашения не показывается ни жетоном, ни текстом."""
    client.force_login(world["student"])
    for url in ("/courses/", f"/courses/{world['course'].pk}/"):
        html = client.get(url).content.decode()
        assert world["course"].invite_code not in html


# ---------------------------------------------------------------- AC-28


def _error_cases(client, world):
    """(описание, ответ, ожидаемый статус, текст ссылки возврата или None для /главн/)."""
    other_teacher = TeacherFactory(username="prof_other_style")
    pk = world["course"].pk
    yield "404 гость", client.get("/no-such-page-style/"), 404, None
    client.force_login(world["student"])
    yield "404 студент", client.get("/no-such-page-style/"), 404, None
    yield "404 студент, курс", client.get("/courses/999999/"), 404, None
    yield "403 студент, manage", client.get(f"/courses/{pk}/manage/"), 403, None
    client.force_login(other_teacher)
    yield "403 чужой преподаватель", client.get(f"/courses/{pk}/manage/"), 403, None
    yield "405 чужой преподаватель", client.get(f"/courses/{pk}/groups/add/"), 405, None
    client.force_login(world["owner"])
    yield "405 владелец", client.get(f"/courses/{pk}/groups/add/"), 405, "Вернуться к курсу"


def test_error_pages_have_decorative_code_and_single_way_back(client, world):
    """AC-28: 403/404/405 — .error-code (aria-hidden), h1 по-русски, одна ссылка возврата."""
    for name, response, status, back in _error_cases(client, world):
        assert response.status_code == status, name
        html = response.content.decode()
        tree = parse(html)
        assert tree.find("header") is not None, name
        main = _main(response)
        codes = _by_class(main, "error-code")
        assert len(codes) == 1, f"{name}: .error-code {len(codes)}"
        assert codes[0].attrs.get("aria-hidden") == "true", name
        assert codes[0].text == str(status), name
        h1s = main.find_all("h1")
        assert len(h1s) == 1 and re.search(r"[А-Яа-яЁё]", h1s[0].text), name
        home_links = [a for a in main.find_all("a") if HOME_LINK.search(a.text)]
        if back is None:
            assert len(home_links) == 1, f"{name}: ссылок на главную {len(home_links)}"
            assert home_links[0].attrs.get("href") == "/"
        else:
            assert home_links == [], name
            assert len(_links(main, back)) == 1, name
        for leak in ENGLISH_LEAKS:
            assert leak not in html, f"{name}: видно «{leak}»"
        assert "no-such-page-style" not in html, name


def test_error_pages_highlight_no_section(client, world):
    """AC-8 (решение 7): на страницах ошибок ни одна ссылка nav не текущая."""
    for name, response, _status, _back in _error_cases(client, world):
        assert _current_links(response) == [], f"{name}: подсвечен раздел"
