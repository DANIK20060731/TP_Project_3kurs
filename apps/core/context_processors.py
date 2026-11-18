"""Контекст-процессоры шаблонов: текущий раздел шапки."""

from django.http import HttpRequest

# Разделы шапки с отдельной ссылкой; прочие маршруты этих приложений — «Мои курсы».
_COURSE_SECTIONS = {"enroll": "enroll", "create": "create"}
_COURSE_NAMESPACES = {"courses", "assignments"}


def nav_section(request: HttpRequest) -> dict[str, str]:
    """Раздел шапки для ``aria-current``: "courses", "enroll", "create" или "".

    Берётся из ``request.resolver_match``; без него (404 до разрешения адреса) — "".
    О пользователе в контекст ничего не кладётся.
    """
    match = getattr(request, "resolver_match", None)
    section = ""
    if match is not None and match.namespace in _COURSE_NAMESPACES:
        section = "courses"
        if match.namespace == "courses":
            section = _COURSE_SECTIONS.get(match.url_name or "", "courses")
    return {"nav_section": section}
