"""T-017: статический разбор ``static/css/app.css`` (AC-1, AC-2, AC-4, AC-5, AC-27, AC-29c).

Чистый Python, без Django и браузера: файл читается как текст и делится на блоки
утилитами ``tests/unit/core/css_tools.py``.
"""

import re

import pytest

from tests.unit.core.css_tools import (
    COLOR_LITERAL_RE,
    blocks,
    header_comment,
    is_root,
    raw_css,
    root_variables,
    strip_comments,
)

TOKEN_GROUPS = ["--color-", "--font-", "--space-", "--radius-", "--shadow-"]
GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "system-ui", "ui-monospace", "ui-serif"}


@pytest.fixture(scope="module")
def css() -> str:
    return raw_css()


# ---------------------------------------------------------------- AC-1


@pytest.mark.parametrize("prefix", TOKEN_GROUPS)
def test_root_declares_every_token_group(css, prefix):
    """AC-1: в :root объявлена хотя бы одна переменная каждой группы токенов."""
    names = root_variables(css)
    assert [n for n in names if n.startswith(prefix)], (
        f"в :root нет ни одной переменной {prefix}*; есть {sorted(names)}"
    )


# ---------------------------------------------------------------- AC-2


def test_color_literals_only_inside_root(css):
    """AC-2: литералы цвета (#hex, rgb(, hsl() встречаются только в блоках :root."""
    leaks = []
    for preludes, body in blocks(css):
        if is_root(preludes):
            continue
        for match in COLOR_LITERAL_RE.finditer(body):
            leaks.append(f"{' > '.join(preludes)}: {match.group(0)}")
    assert leaks == [], f"литералы цвета вне :root: {leaks}"


def test_root_tokens_hold_the_palette(css):
    """AC-2: палитра задана токенами — в :root есть литералы цвета, правила ссылаются на var()."""
    root_values = " ".join(root_variables(css).values())
    assert COLOR_LITERAL_RE.search(root_values), "в :root нет ни одного цвета"
    non_root = " ".join(body for preludes, body in blocks(css) if not is_root(preludes))
    assert "var(--color-" in non_root, "правила не используют цветовые токены"


# ---------------------------------------------------------------- AC-4


def test_css_urls_are_local(css):
    """AC-4: каждый url(…) в app.css локальный: без схемы (http:, data:) и без //."""
    urls = re.findall(r"url\(\s*([^)]*?)\s*\)", strip_comments(css))
    bad = []
    for raw in urls:
        value = raw.strip("'\"")
        if value.startswith("//") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
            bad.append(value)
    assert bad == [], f"внешние или data-адреса в app.css: {bad}"


def test_css_has_no_external_schemes_even_in_comments(css):
    """AC-4: подстрок http:// и https:// нет во всём файле, включая комментарии."""
    assert "http://" not in css
    assert "https://" not in css


# ---------------------------------------------------------------- AC-5 (шрифты не согласованы)


def test_no_font_face_without_agreed_fonts(css):
    """AC-5: шрифты не согласованы (решение 2) — в app.css нет @font-face."""
    assert "@font-face" not in strip_comments(css)


def _families(value: str) -> list[str]:
    return [part.strip().strip("'\"").lower() for part in value.split(",") if part.strip()]


def test_font_tokens_are_system_stacks(css):
    """AC-5: каждый --font-* — системный стек: без url() и с родовым семейством в конце."""
    fonts = {n: v for n, v in root_variables(css).items() if n.startswith("--font-")}
    assert fonts, "нет шрифтовых токенов --font-*"
    for name, value in fonts.items():
        assert "url(" not in value, f"{name} ссылается на файл шрифта"
        families = _families(value)
        assert families[-1] in GENERIC_FAMILIES, f"{name} не кончается родовым семейством: {value}"


def test_font_tokens_cover_serif_sans_and_mono(css):
    """AC-5 (направление A): есть стеки антиквы (serif), гротеска и моноширинного."""
    finals = {
        _families(v)[-1]
        for n, v in root_variables(css).items()
        if n.startswith("--font-") and _families(v)
    }
    assert "serif" in finals, "нет системного стека антиквы (… serif)"
    assert "sans-serif" in finals or "system-ui" in finals, "нет системного стека гротеска"
    assert "monospace" in finals, "нет моноширинного стека (… monospace)"


# ---------------------------------------------------------------- AC-29c (статическая часть)


def test_motion_is_guarded_by_prefers_reduced_motion(css):
    """AC-29c: если есть transition/animation/@keyframes — есть блок prefers-reduced-motion."""
    body = strip_comments(css)
    if not re.search(r"\btransition\b|\banimation\b|@keyframes", body):
        pytest.skip("в app.css нет анимаций и переходов")
    preludes = {p for chain, _ in blocks(css) for p in chain}
    assert any(
        re.fullmatch(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)", p) for p in preludes
    ), "нет блока @media (prefers-reduced-motion: reduce)"


# ---------------------------------------------------------------- AC-27 (шапка-комментарий)

NEW_CLASSES = [
    ".badge-role",
    ".badge-phase--",
    ".card",
    ".stretched-link",
    ".token",
    ".table-stack",
    ".error-code",
]


@pytest.mark.parametrize("cls", NEW_CLASSES)
def test_header_comment_lists_new_classes(css, cls):
    """AC-27: шапка-комментарий app.css перечисляет новые классы T-017."""
    assert cls in header_comment(css), f"в шапке-комментарии нет {cls}"


@pytest.mark.parametrize("cls", NEW_CLASSES)
def test_new_classes_are_styled(css, cls):
    """AC-27: каждый новый класс из шапки действительно описан правилом CSS."""
    selectors = " ".join(p for chain, _ in blocks(css) for p in chain)
    assert re.search(re.escape(cls) + r"[\w-]*", selectors), f"нет правила для {cls}"


def test_header_comment_classes_exist_in_rules(css):
    """AC-27: классы, названные в шапке-комментарии, не устарели — у каждого есть правило."""
    comment = header_comment(css)
    named = set(re.findall(r"(?<![\w/.-])\.([a-z][\w-]*)", comment))
    selectors = " ".join(p for chain, _ in blocks(css) for p in chain)
    missing = sorted(n for n in named if not re.search(r"\." + re.escape(n), selectors))
    assert missing == [], f"классы из шапки без правил: {missing}"
