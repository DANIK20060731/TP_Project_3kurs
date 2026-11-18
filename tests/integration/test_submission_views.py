from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import Assignment
from apps.submissions.models import Submission, SubmissionAuthor
from apps.submissions.services import save_submission
from tests.factories import AssignmentFactory, EnrollmentFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def work(settings, tmp_path):
    settings.SUBMISSION_ROOT = tmp_path
    assignment = AssignmentFactory(
        allowed_formats=["txt"], max_file_size_mb=1, kind=Assignment.Kind.TEAM
    )
    author = EnrollmentFactory(course=assignment.course).student
    teammate = EnrollmentFactory(course=assignment.course).student
    return assignment, author, teammate


def _upload(content=b"first", name="do-not-disclose.txt"):
    return SimpleUploadedFile(name, content)


def _form_url(assignment):
    return reverse("submissions:submission", args=[assignment.pk])


def _download_url(code):
    return reverse("submissions:submission_download", args=[code])


def test_team_submission_replacement_and_private_download(
    client, work, django_capture_on_commit_callbacks
):
    assignment, author, teammate = work
    client.force_login(author)
    url = _form_url(assignment)
    assert teammate.username not in client.get(url).content.decode()
    response = client.post(url, {"file": _upload(), "coauthors": teammate.username})
    assert response.status_code == 302
    submission = Submission.objects.get()
    code, old_key = submission.public_code, submission.file_key
    assert "do-not-disclose" not in old_key

    client.force_login(teammate)
    page = client.get(url).content.decode()
    assert str(code) in page
    assert author.username not in page
    response = client.get(_download_url(code))
    assert response.status_code == 200
    assert response["Content-Disposition"] == f'attachment; filename="{code}.txt"'
    assert b"".join(response.streaming_content) == b"first"
    assert client.post(url, {"file": _upload(b"forbidden")}).status_code == 404

    client.force_login(author)
    assert teammate.username in client.get(url).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url, {"file": _upload(b"second")}).status_code == 302
    submission.refresh_from_db()
    assert submission.public_code == code
    assert submission.file_key != old_key
    assert b"".join(client.get(_download_url(code)).streaming_content) == b"second"
    client.force_login(teammate)
    assert client.get(_download_url(code)).status_code == 404


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("bad.pdf", b"%PDF-"),
        ("empty.txt", b""),
        ("wrong.txt", b"\x00binary"),
        ("big.txt", b"a" * (1024**2 + 1)),
        (None, None),
    ],
)
def test_bad_replacement_preserves_file_and_authors(client, work, name, content):
    assignment, author, teammate = work
    previous = save_submission(author, assignment.pk, _upload(), [teammate.username])
    client.force_login(author)
    url = _form_url(assignment)
    response = client.post(url, {"file": _upload(content, name)} if name else {})
    assert response.context["form"].errors["file"]
    current = Submission.objects.get()
    assert current.file_key == previous.file_key
    assert current.authors.filter(student=teammate).exists()


def test_deadline_boundary_and_permissions(client, work):
    assignment, author, teammate = work
    outsider = UserFactory()
    url = _form_url(assignment)
    assert client.get(url).status_code == 302
    client.force_login(outsider)
    assert client.get(url).status_code == 404
    assert client.post(url, {"file": _upload()}).status_code == 404

    with freeze_time(assignment.submission_deadline - timedelta(seconds=1)):
        submission = save_submission(author, assignment.pk, _upload(b"a" * 1024**2), [])
    download = _download_url(submission.public_code)
    assert client.get(download).status_code == client.get(_download_url(uuid4())).status_code == 404
    client.force_login(author)
    with freeze_time(assignment.submission_deadline):
        assert client.post(url, {"file": _upload()}).status_code == 400
        with pytest.raises(ValidationError, match="Срок сдачи истёк"):
            save_submission(teammate, assignment.pk, _upload(), [])
        response = client.get(download)
        assert response.status_code == 200
        response.close()


def test_invalid_coauthors_and_database_membership_constraint(client, work):
    assignment, author, teammate = work
    outsider = UserFactory()
    client.force_login(author)
    url = _form_url(assignment)
    for usernames in (
        author.username,
        outsider.username,
        f"{teammate.username} {teammate.username}",
    ):
        response = client.post(url, {"file": _upload(), "coauthors": usernames})
        assert response.context["form"].errors["coauthors"]
        assert not Submission.objects.exists()

    first = save_submission(teammate, assignment.pk, _upload(), [])
    response = client.post(url, {"file": _upload(), "coauthors": teammate.username})
    assert response.context["form"].errors["coauthors"]

    second = save_submission(author, assignment.pk, _upload(), [])
    with pytest.raises(IntegrityError), transaction.atomic():
        SubmissionAuthor.objects.create(
            assignment=assignment, submission=second, student=first.submitted_by
        )


def test_individual_rejects_crafted_coauthors_and_requires_csrf(work):
    assignment, author, teammate = work
    assignment.kind = Assignment.Kind.INDIVIDUAL
    assignment.save(update_fields=["kind"])
    url = _form_url(assignment)
    client = Client(enforce_csrf_checks=True)
    client.force_login(author)
    assert "coauthors" not in client.get(url).context["form"].fields
    assert client.post(url, {"file": _upload()}).status_code == 403
    response = client.post(
        url,
        {"file": _upload(), "coauthors": teammate.username},
        headers={"X-CSRFToken": client.cookies["csrftoken"].value},
    )
    assert response.context["form"].non_field_errors()
    assert not Submission.objects.exists()


def test_failed_database_write_keeps_current_file(work, settings, monkeypatch):
    assignment, author, _ = work
    first = save_submission(author, assignment.pk, _upload(), [])

    def fail(*args, **kwargs):
        raise IntegrityError("test failure")

    monkeypatch.setattr(Submission, "save", fail)
    with pytest.raises(IntegrityError, match="test failure"):
        save_submission(author, assignment.pk, _upload(b"replacement"), [])
    assert Submission.objects.get().file_key == first.file_key
    directory = Path(settings.SUBMISSION_ROOT)
    assert list(directory.iterdir()) == [directory / first.file_key]


@pytest.mark.django_db(transaction=True)
def test_concurrent_team_submissions_assign_coauthor_once(work):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    if connection.vendor == "sqlite" and connection.creation.is_in_memory_db(
        connection.settings_dict["NAME"]
    ):
        pytest.skip("The shared in-memory SQLite test database does not wait for write locks.")

    assignment, author, teammate = work
    another_author = EnrollmentFactory(course=assignment.course).student
    ready = Barrier(2, timeout=10)

    def submit(student):
        try:
            ready.wait()
            save_submission(student, assignment.pk, _upload(), [teammate.username])
            return True
        except ValidationError as exc:
            assert "Участник уже входит в другую работу." in exc.message_dict["coauthors"]
            return False
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, [author, another_author])) == [False, True]
    assert Submission.objects.count() == 1
    assert SubmissionAuthor.objects.filter(assignment=assignment, student=teammate).count() == 1


def test_download_loads_new_file_if_replaced_during_request(
    client, work, monkeypatch, django_capture_on_commit_callbacks
):
    from django.core.files.storage import FileSystemStorage

    assignment, author, _ = work
    submission = save_submission(author, assignment.pk, _upload(), [])
    storage_open = FileSystemStorage.open

    def open_after_replacement(storage, name, mode):
        if name == submission.file_key:
            with django_capture_on_commit_callbacks(execute=True):
                save_submission(author, assignment.pk, _upload(b"updated"), [])
        return storage_open(storage, name, mode)

    monkeypatch.setattr(FileSystemStorage, "open", open_after_replacement)
    client.force_login(author)
    response = client.get(_download_url(submission.public_code))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"updated"
