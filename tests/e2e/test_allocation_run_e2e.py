"""T-008: распределение, анонимный список и ручное переназначение в браузере."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Criterion, Rubric, ScaleLevel
from apps.reviews.models import AllocationRun, ReviewAssignment
from apps.submissions.models import Submission, SubmissionAuthor
from tests.factories import AssignmentFactory, EnrollmentFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _sign_in(page: Page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}{reverse('accounts:login')}")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{base_url}/")


def test_owner_allocates_and_student_sees_only_assigned_code(browser, page, live_server):
    now = timezone.now()
    assignment = AssignmentFactory(
        submission_deadline=now - timedelta(hours=1),
        review_deadline=now + timedelta(hours=1),
        reviews_per_submission=1,
    )
    criterion = Criterion.objects.create(
        rubric=Rubric.objects.create(assignment=assignment),
        title="Полнота решения",
        weight=1,
    )
    ScaleLevel.objects.create(criterion=criterion, points=1, description="Выполнено")
    works = []
    for index in range(3):
        author = EnrollmentFactory(
            course=assignment.course, student__username=f"allocation-student-{index}"
        ).student
        work = Submission.objects.create(
            assignment=assignment, submitted_by=author, file_key=f"allocation-{index}.txt"
        )
        SubmissionAuthor.objects.create(assignment=assignment, submission=work, student=author)
        works.append(work)

    base_url = live_server.url
    detail_url = f"{base_url}{reverse('assignments:detail', args=[assignment.pk])}"
    manage_url = f"{base_url}{reverse('reviews:manage', args=[assignment.pk])}"
    _sign_in(page, base_url, assignment.course.owner.username)
    page.goto(detail_url)
    page.get_by_role("button", name="Распределить", exact=True).click()
    expect(page).to_have_url(manage_url)
    expect(page.get_by_role("heading", name="Распределение рецензий")).to_be_visible()

    run = AllocationRun.objects.get(assignment=assignment)
    row = ReviewAssignment.objects.select_related("reviewer").get(run=run, submission=works[0])
    code = str(works[0].public_code)
    review_table = page.get_by_role("table", name="Назначения на рецензирование")
    review_row = review_table.get_by_role("row").filter(has_text=code)
    expect(review_row).to_contain_text(row.reviewer.username)

    student_page = browser.new_page()
    try:
        _sign_in(student_page, base_url, row.reviewer.username)
        student_page.goto(detail_url)
        assigned = student_page.get_by_role("region", name="Работы для рецензирования")
        expect(assigned.get_by_role("listitem")).to_have_text([code])
        rendered = student_page.content()
        assert str(run.seed) not in rendered
        assert works[0].submitted_by.username not in rendered
        assert works[0].submitted_by.email not in rendered
        assert all(str(work.public_code) not in rendered for work in works[1:])
        expect(student_page.get_by_role("button", name="Распределить")).to_have_count(0)
    finally:
        student_page.close()

    review_row.get_by_role(
        "link", name=f"Переназначить рецензию {row.reviewer.username} на работу {code}"
    ).click()
    page.get_by_label("Новый рецензент").select_option(str(works[0].submitted_by_id))
    page.get_by_role("button", name="Сохранить назначение").click()
    expect(page.get_by_text("Студент не может рецензировать работу своей команды.")).to_be_visible()
    assert ReviewAssignment.objects.get(pk=row.pk).reviewer_id == row.reviewer_id
