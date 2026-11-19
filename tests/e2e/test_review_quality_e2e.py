"""Браузерный сценарий модерации флага после отправки рецензии."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from apps.reviews.models import Review, ReviewAssignment
from apps.reviews.services import run_allocation
from tests.integration.test_allocation_run import assignment_for_allocation

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _sign_in(page: Page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}{reverse('accounts:login')}")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{base_url}/")


def test_teacher_moderates_flag_and_student_sees_no_quality_details(browser, page, live_server):
    assignment, _, _ = assignment_for_allocation((1, 1, 1))
    run = run_allocation(assignment.course.owner, assignment.pk)
    row = ReviewAssignment.objects.select_related("submission", "reviewer").filter(run=run).first()
    assert row is not None
    base_url = live_server.url
    assignment_url = f"{base_url}{reverse('assignments:detail', args=[assignment.pk])}"
    quality_url = f"{base_url}{reverse('reviews:quality', args=[assignment.pk])}"
    quality_link = "Качество рецензий"
    reason = "Значимых слов в комментарии"

    student = browser.new_page()
    try:
        _sign_in(student, base_url, row.reviewer.username)
        student.goto(assignment_url)
        expect(student.get_by_role("link", name=quality_link)).to_have_count(0)
        assert student.request.get(quality_url).status == 404
        student.get_by_role("link", name=str(row.submission.public_code)).click()
        assert row.submission.submitted_by.username not in student.content()
        level = assignment.rubric.criteria.get().levels.get()
        student.get_by_label("Уровень", exact=False).select_option(str(level.pk))
        student.get_by_label("Общий комментарий").fill("Нормально")
        student.get_by_role("button", name="Отправить рецензию").click()
        expect(student.get_by_role("status")).to_contain_text("Рецензия отправлена.")
        review = Review.objects.get(assignment=row)
        code = str(review.public_code)

        _sign_in(page, base_url, assignment.course.owner.username)
        page.goto(assignment_url)
        page.get_by_role("link", name=quality_link).click()
        expect(page).to_have_url(quality_url)
        flagged = page.get_by_role("article").filter(has_text=code)
        expect(flagged.get_by_text("Нормально", exact=True)).to_be_visible()
        flag = flagged.get_by_role("listitem").filter(has_text=reason)
        flag.get_by_role("button", name="Отклонить флаг").click()
        expect(flag.get_by_text("Флаг отклонён.")).to_be_visible()
        flagged.get_by_role("button", name="Аннулировать рецензию").click()
        expect(page.get_by_role("heading", name="Аннулированные рецензии")).to_be_visible()
        expect(page.get_by_text(code, exact=True)).to_be_visible()

        student.reload()
        expect(student.get_by_text("Редактирование этой рецензии недоступно.")).to_be_visible()
        expect(student.get_by_role("button", name="Сохранить", exact=True)).to_have_count(0)
        html = student.content()
        assert all(value not in html for value in (reason, code, quality_url, "Флаг отклонён"))
    finally:
        student.close()
