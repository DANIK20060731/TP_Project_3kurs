"""Помощники разбора HTML для integration-тестов курсов (T-002)."""

from tests.integration.core.html_tree import Element, parse


def header(response) -> Element:
    el = parse(response.content).find("header")
    assert el is not None, "в странице нет <header>"
    return el


def main(response) -> Element:
    el = parse(response.content).find("main")
    assert el is not None, "в странице нет <main>"
    return el


def links(el: Element, text: str) -> list[Element]:
    return [a for a in el.find_all("a") if a.text == text]


def alerts(response) -> list[Element]:
    return parse(response.content).find_all(role="alert")


def group_sections(response) -> dict[str, Element]:
    """Секции <section> страницы управления: заголовок (h2/h3) → секция."""
    result: dict[str, Element] = {}
    for section in main(response).find_all("section"):
        heading = next((el for el in section.iter() if el.tag in {"h2", "h3"}), None)
        if heading is not None:
            result[heading.text] = section
    return result


def section_for(response, needle: str) -> Element:
    """Секция, в заголовке которой есть ``needle`` (номер группы или «Без группы»)."""
    matches = [s for title, s in group_sections(response).items() if needle in title]
    assert len(matches) == 1, f"ожидалась одна секция с заголовком «{needle}», есть {matches}"
    return matches[0]
