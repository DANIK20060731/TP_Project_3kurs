"""Выдача файла работы под публичным кодом."""

from pathlib import PurePosixPath

from django.http import FileResponse

from .models import Submission
from .services import submission_storage


def work_attachment(submission: Submission) -> FileResponse:
    stream = submission_storage().open(submission.file_key, "rb")
    suffix = PurePosixPath(submission.file_key).suffix
    return FileResponse(
        stream,
        as_attachment=True,
        filename=f"{submission.public_code}{suffix}",
        content_type="application/octet-stream",
    )
