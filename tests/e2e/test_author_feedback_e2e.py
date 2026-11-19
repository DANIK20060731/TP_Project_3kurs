"""Браузерный сценарий получения рецензий и изменения итога преподавателем."""

import re

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Assignment
from tests.integration.test_author_feedback import feedback_case as feedback_case

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _sign_in(page: Page, base: str, username: str) -> None:
    page.goto(f"{base}{reverse('accounts:login')}")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{base}/")


def test_author_reads_reviews_and_owner_changes_grade(browser, page, live_server, feedback_case):
    assignment, works, teams, reviews = feedback_case
    base = live_server.url
    author_page = browser.new_page()
    try:
        _sign_in(author_page, base, teams[0][1].username)
        author_page.goto(f"{base}{reverse('submissions:submission', args=[assignment.pk])}")
        feedback_link = author_page.get_by_role("link", name="Рецензии и итоговая оценка")
        expect(feedback_link).to_have_count(0)
        now = timezone.now()
        Assignment.objects.filter(pk=assignment.pk).update(review_deadline=now)
        author_page.reload()
        feedback_link.click()
        expect(author_page.get_by_text(re.compile(r"^35[,.]71%$"))).to_be_visible()
        expect(author_page.get_by_text("Опубликованный комментарий 1")).to_be_visible()
        expect(author_page.get_by_text("Секретный черновик")).to_have_count(0)
        assert reviews[0].assignment.reviewer.username not in author_page.content()

        _sign_in(page, base, assignment.course.owner.username)
        page.goto(f"{base}{reverse('assignments:detail', args=[assignment.pk])}")
        page.get_by_role("link", name="Итоговые оценки").click()
        page.get_by_role("link", name=str(works[0].public_code)).click()
        page.get_by_label("Ручной итог, %").fill("72,5")
        page.get_by_role("button", name="Сохранить итог").click()
        expect(page.get_by_text("Итоговая оценка обновлена.")).to_be_visible()
        author_page.reload()
        expect(author_page.get_by_text(re.compile(r"^72[,.]50?%$"))).to_be_visible()
    finally:
        author_page.close()
