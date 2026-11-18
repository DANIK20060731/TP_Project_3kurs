"""Права, проверка файла и сохранение сдачи."""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import UploadedFile
from django.db import connection, transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.courses.models import Enrollment

from .models import Submission, SubmissionAuthor

logger = logging.getLogger(__name__)


def submission_storage() -> FileSystemStorage:
    return FileSystemStorage(location=settings.SUBMISSION_ROOT, file_permissions_mode=0o600)


def student_assignments(student: User) -> QuerySet[Assignment]:
    return Assignment.objects.filter(
        course__enrollments__student=student, course__enrollments__student__role=User.Role.STUDENT
    )


def student_submissions(student: User) -> QuerySet[Submission]:
    return Submission.objects.filter(
        assignment__in=student_assignments(student), authors__student=student
    )


def _file_extension(assignment: Assignment, upload: UploadedFile[bytes]) -> str:
    extension = PurePosixPath(upload.name or "").suffix.lower().removeprefix(".")
    if extension not in assignment.allowed_formats:
        raise ValidationError({"file": "Формат файла не разрешён для этого задания."})
    if upload.size is None or not 0 < upload.size <= assignment.max_file_size_mb * 1024 * 1024:
        raise ValidationError({"file": "Файл пуст или превышает допустимый размер."})

    try:
        if extension == "pdf":
            valid = upload.read(5) == b"%PDF-"
        elif extension in {"zip", "docx", "odt"}:
            with ZipFile(upload) as archive:
                names = set(archive.namelist())
                if extension == "docx":
                    valid = {"[Content_Types].xml", "word/document.xml"} <= names
                elif extension == "odt":
                    media_type = b"application/vnd.oasis.opendocument.text"
                    valid = {"mimetype", "content.xml"} <= names
                    if valid:
                        entry = archive.getinfo("mimetype")
                        valid = (
                            entry.compress_type == ZIP_STORED
                            and entry.file_size == len(media_type)
                            and archive.read(entry) == media_type
                        )
                else:
                    valid = True
        else:
            content = upload.read().decode("utf-8-sig")
            valid = "\x00" not in content
            if extension == "ipynb":
                notebook = json.loads(content)
                valid = isinstance(notebook, dict) and isinstance(notebook.get("cells"), list)
    except (BadZipFile, ValueError, NotImplementedError, RuntimeError, RecursionError):
        valid = False
    finally:
        upload.seek(0)
    if not valid:
        raise ValidationError({"file": "Содержимое файла не соответствует формату."})
    return extension


def _author_ids(assignment: Assignment, student: User, usernames: list[str]) -> set[int]:
    if usernames and assignment.kind != Assignment.Kind.TEAM:
        raise ValidationError({"coauthors": "Соавторы допустимы только в командном задании."})
    if student.username in usernames or len(set(usernames)) != len(usernames):
        raise ValidationError({"coauthors": "Укажите неповторяющиеся логины соавторов."})
    ids = set(
        Enrollment.objects.filter(
            course_id=assignment.course_id,
            student__role=User.Role.STUDENT,
            student__username__in=usernames,
        ).values_list("student_id", flat=True)
    )
    if len(ids) != len(usernames):
        raise ValidationError({"coauthors": "Проверьте логины соавторов из вашего курса."})
    return ids | {student.pk}


def save_submission(
    student: User, assignment_pk: int, upload: UploadedFile[bytes], usernames: list[str]
) -> Submission:
    """Сериализует изменения по заданию, включая проверку дедлайна и состава."""
    storage = submission_storage()
    new_key = ""
    try:
        with transaction.atomic(durable=True):
            assignments = student_assignments(student).filter(pk=assignment_pk)
            if connection.vendor == "sqlite":
                # SQLite не поддерживает SELECT FOR UPDATE. Первая операция
                # должна начать запись, иначе конкурирующие чтения блокируют обновление.
                assignments.update(id=F("id"))
            assignment = assignments.select_for_update(of=("self",)).get()
            current = student_submissions(student).filter(assignment=assignment).first()
            if current and current.submitted_by_id != student.pk:
                raise Submission.DoesNotExist
            if timezone.now() >= assignment.submission_deadline:
                raise ValidationError("Срок сдачи истёк.")
            extension = _file_extension(assignment, upload)
            ids = _author_ids(assignment, student, usernames)
            if (
                SubmissionAuthor.objects.filter(assignment=assignment, student_id__in=ids)
                .exclude(submission=current)
                .exists()
            ):
                raise ValidationError({"coauthors": "Участник уже входит в другую работу."})
            submission = current or Submission(assignment=assignment, submitted_by=student)
            old_key = submission.file_key
            new_key = storage.save(f"{uuid4().hex}.{extension}", upload)
            if timezone.now() >= assignment.submission_deadline:
                raise ValidationError("Срок сдачи истёк.")
            submission.file_key = new_key
            submission.save()
            submission.authors.exclude(student_id__in=ids).delete()
            existing = set(submission.authors.values_list("student_id", flat=True))
            SubmissionAuthor.objects.bulk_create(
                [
                    SubmissionAuthor(submission=submission, assignment=assignment, student_id=pk)
                    for pk in ids - existing
                ]
            )
            if old_key:
                transaction.on_commit(lambda: storage.delete(old_key), robust=True)
    except Exception:
        if new_key:
            try:
                storage.delete(new_key)
            except OSError:
                logger.exception("Не удалось удалить файл после отката сдачи.")
        raise
    return submission
