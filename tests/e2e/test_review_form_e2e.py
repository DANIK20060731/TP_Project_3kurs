"""Браузерный сценарий анонимной рецензии с реальным HTMX-автосохранением."""

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from apps.reviews.models import Review, ReviewAssignment
from apps.reviews.services import run_allocation
from tests.integration.test_allocation_run import assignment_for_allocation

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_student_autosaves_submits_and_edits_review(page, live_server, settings, tmp_path):
    assignment, _, _ = assignment_for_allocation((1, 1, 1))
    run = run_allocation(assignment.course.owner, assignment.pk)
    row = ReviewAssignment.objects.select_related("submission", "reviewer").filter(run=run).first()
    assert row is not None
    code = str(row.submission.public_code)
    settings.SUBMISSION_ROOT = tmp_path
    (tmp_path / row.submission.file_key).write_bytes(b"submitted work")
    base = live_server.url
    page.goto(f"{base}{reverse('accounts:login')}")
    page.get_by_label("Имя пользователя").fill(row.reviewer.username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{base}/")
    page.goto(f"{base}{reverse('assignments:detail', args=[assignment.pk])}")
    page.get_by_role("link", name=code).click()

    with page.expect_download() as file:
        page.get_by_role("link", name="Скачать работу").click()
    assert file.value.suggested_filename == f"{code}.txt"
    assert row.submission.submitted_by.username not in page.content()

    level = assignment.rubric.criteria.get().levels.get()
    select = page.get_by_label("Уровень", exact=False)
    comment = page.get_by_label("Общий комментарий")
    with page.expect_response(lambda response: response.url.endswith("/autosave/")) as response:
        select.select_option(str(level.pk))
        comment.fill("Первый комментарий")
    assert response.value.ok
    expect(page.get_by_role("status")).to_contain_text("Черновик сохранён.")
    page.reload()
    expect(select).to_have_value(str(level.pk))
    expect(comment).to_have_value("Первый комментарий")

    pending = []
    page.route("**/autosave/", lambda route: pending.append(route), times=1)
    with page.expect_request(lambda request: request.url.endswith("/autosave/")):
        comment.fill("Готово к отправке")
    page.get_by_role("button", name="Отправить рецензию").click()
    comment.focus()
    assert len(pending) == 1
    pending[0].continue_()
    expect(page.get_by_role("button", name="Отправить рецензию")).to_have_count(0)
    review = Review.objects.get(assignment=row)
    assert review.submitted_at is not None
    assert review.comment == "Готово к отправке"
    submitted_at = review.submitted_at

    comment.fill("Правка отправленной рецензии")
    expect(page.get_by_role("status")).to_contain_text("Правки сохранены.")
    page.reload()
    expect(comment).to_have_value("Правка отправленной рецензии")
    review.refresh_from_db()
    assert review.submitted_at == submitted_at
