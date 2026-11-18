"""T-003: согласованные пути маршрутов (ссылки в шаблонах проверяются точными href)."""

from django.urls import reverse


def test_assignment_urls_resolve_to_agreed_paths():
    """AC-1/AC-5/AC-6/AC-7: имена маршрутов дают согласованные пути."""
    assert reverse("assignments:create", args=[7]) == "/courses/7/assignments/create/"
    assert reverse("assignments:detail", args=[3]) == "/assignments/3/"
    assert reverse("assignments:edit", args=[3]) == "/assignments/3/edit/"
    assert reverse("courses:detail", args=[7]) == "/courses/7/"
