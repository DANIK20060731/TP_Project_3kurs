"""Браузерный сценарий сдачи командной работы."""

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Assignment
from tests.factories import AssignmentFactory, EnrollmentFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _sign_in(page: Page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{base_url}/")


def test_team_can_download_replacement_after_deadline(browser, live_server, settings, tmp_path):
    settings.SUBMISSION_ROOT = tmp_path / "storage"
    assignment = AssignmentFactory(kind=Assignment.Kind.TEAM, allowed_formats=["txt"])
    author = EnrollmentFactory(course=assignment.course).student
    teammate = EnrollmentFactory(course=assignment.course).student
    base_url = live_server.url
    assignment_url = f"{base_url}/assignments/{assignment.pk}/"
    file = tmp_path / "original-name.txt"
    file.write_text("первая версия", encoding="utf-8")

    author_page = browser.new_page()
    team_page = browser.new_page()
    try:
        _sign_in(author_page, base_url, author.username)
        author_page.goto(assignment_url)
        author_page.get_by_role("link", name="Сдача работы").click()
        author_page.get_by_label("Файл работы").set_input_files(file)
        author_page.get_by_label("Логины соавторов").fill(teammate.username)
        author_page.get_by_role("button", name="Сдать работу").click()
        expect(author_page.get_by_role("link", name="Скачать работу")).to_be_visible()
        code = author_page.locator(".token").inner_text()

        _sign_in(team_page, base_url, teammate.username)
        team_page.goto(assignment_url)
        team_page.get_by_role("link", name="Сдача работы").click()
        expect(team_page.locator(".token")).to_have_text(code)
        expect(team_page.get_by_label("Файл работы")).to_have_count(0)
        with team_page.expect_download() as pending:
            team_page.get_by_role("link", name="Скачать работу").click()
        assert pending.value.suggested_filename == f"{code}.txt"
        assert pending.value.path().read_text(encoding="utf-8") == "первая версия"

        file.write_text("новая версия", encoding="utf-8")
        author_page.get_by_label("Файл работы").set_input_files(file)
        author_page.get_by_role("button", name="Заменить файл").click()
        expect(author_page.get_by_text(f"Работа {code} сохранена.")).to_be_visible()

        Assignment.objects.filter(pk=assignment.pk).update(
            submission_deadline=timezone.now() - timedelta(seconds=1)
        )
        author_page.reload()
        expect(author_page.get_by_text("Срок сдачи истёк.")).to_be_visible()
        expect(author_page.get_by_label("Файл работы")).to_have_count(0)
        team_page.reload()
        with team_page.expect_download() as pending:
            team_page.get_by_role("link", name="Скачать работу").click()
        assert pending.value.path().read_text(encoding="utf-8") == "новая версия"
    finally:
        author_page.close()
        team_page.close()
