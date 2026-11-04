"""Мини-DOM на stdlib ``html.parser`` для проверок разметки в integration-тестах.

Без новых зависимостей: строит дерево элементов, умеет искать по тегу и атрибутам
и возвращать текст элемента с нормализованными пробелами.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list)
    parent: Element | None = None

    @property
    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def iter(self):
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, **attrs: str) -> list[Element]:
        result = []
        for el in self.iter():
            if tag is not None and el.tag != tag:
                continue
            if all(el.attrs.get(k.rstrip("_")) == v for k, v in attrs.items()):
                result.append(el)
        return result

    def find(self, tag: str | None = None, **attrs: str) -> Element | None:
        found = self.find_all(tag, **attrs)
        return found[0] if found else None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        el = Element(tag, {k: (v or "") for k, v in attrs}, parent=self.current)
        self.current.children.append(el)
        if tag not in VOID_TAGS:
            self.current = el

    def handle_startendtag(self, tag, attrs):
        el = Element(tag, {k: (v or "") for k, v in attrs}, parent=self.current)
        self.current.children.append(el)

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse(html: str | bytes) -> Element:
    if isinstance(html, bytes):
        html = html.decode()
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root
