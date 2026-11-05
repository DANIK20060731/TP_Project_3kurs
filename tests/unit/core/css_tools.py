"""Разбор ``static/css/app.css`` на чистом Python для тестов T-017.

Без новых зависимостей: снимает комментарии, делит файл на блоки объявлений и
запоминает цепочку прелюдий (``@media …`` → ``:root``) для каждого блока.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parents[3] / "static" / "css" / "app.css"

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
COLOR_LITERAL_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
VAR_DECL_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);?")


def raw_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def strip_comments(css: str) -> str:
    return COMMENT_RE.sub("", css)


def header_comment(css: str) -> str:
    """Первый комментарий файла — шапка с перечнем классов."""
    match = COMMENT_RE.search(css)
    assert match is not None, "в app.css нет шапки-комментария"
    assert css[: match.start()].strip() == "", "шапка-комментарий должна быть в начале app.css"
    return match.group(0)


def blocks(css: str) -> list[tuple[tuple[str, ...], str]]:
    """Список (цепочка прелюдий, текст объявлений) для каждого блока ``{…}``."""
    css = strip_comments(css)
    stack: list[str] = []
    buf: list[str] = []
    result: list[tuple[tuple[str, ...], str]] = []
    for ch in css:
        if ch == "{":
            stack.append(" ".join("".join(buf).split()))
            buf = []
        elif ch == "}":
            body = "".join(buf)
            if body.strip() and stack:
                result.append((tuple(stack), body))
            if stack:
                stack.pop()
            buf = []
        else:
            buf.append(ch)
    return result


def is_root(preludes: tuple[str, ...]) -> bool:
    return bool(preludes) and preludes[-1] == ":root"


def root_variables(css: str) -> dict[str, str]:
    """Переменные из всех блоков ``:root`` (в том числе внутри ``@media``)."""
    result: dict[str, str] = {}
    for preludes, body in blocks(css):
        if is_root(preludes):
            for name, value in VAR_DECL_RE.findall(body):
                result[name] = " ".join(value.split())
    return result
