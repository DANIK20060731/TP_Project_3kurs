"""T-008: запуск, ручное переназначение и анонимная выдача назначений."""

from collections import Counter
from datetime import timedelta
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.assignments.models import Assignment, Criterion, Phase, Rubric, ScaleLevel
from apps.reviews import services
from apps.reviews.models import AllocationRun, ReviewAssignment
from apps.submissions.models import Submission, SubmissionAuthor
from tests.factories import AssignmentFactory, EnrollmentFactory, TeacherFactory

pytestmark = pytest.mark.django_db
SEED = 4242160094500664986


def assignment_for_allocation(team_sizes=(1, 1, 1, 1, 1), *, k=1, rubric=True):
    now = timezone.now()
    assignment = AssignmentFactory(
        submission_deadline=now - timedelta(hours=1),
        review_deadline=now + timedelta(hours=1),
        reviews_per_submission=k,
        kind=Assignment.Kind.TEAM if max(team_sizes) > 1 else Assignment.Kind.INDIVIDUAL,
    )
    if rubric:
        criterion = Criterion.objects.create(
            rubric=Rubric.objects.create(assignment=assignment), title="Критерий", weight=1
        )
        ScaleLevel.objects.create(criterion=criterion, points=1, description="Выполнено")
    works, teams = [], []
    for team_number, size in enumerate(team_sizes):
        team = [EnrollmentFactory(course=assignment.course).student for _ in range(size)]
        work = Submission.objects.create(
            assignment=assignment, submitted_by=team[0], file_key=f"private-work-{team_number}.txt"
        )
        SubmissionAuthor.objects.bulk_create(
            [
                SubmissionAuthor(assignment=assignment, submission=work, student=author)
                for author in team
            ]
        )
        works.append(work)
        teams.append(team)
    return assignment, works, teams


def allocation_url(assignment):
    return reverse("reviews:allocate", args=[assignment.pk])


def detail_url(assignment):
    return reverse("assignments:detail", args=[assignment.pk])


def assert_nothing_allocated(assignment):
    assignment.refresh_from_db()
    assert assignment.allocated_at is None
    assert not AllocationRun.objects.filter(assignment=assignment).exists()
    assert not ReviewAssignment.objects.filter(submission__assignment=assignment).exists()


@pytest.mark.parametrize(
    ("team_sizes", "algorithm"),
    [((1, 1, 1, 1, 1), "circulant"), ((2, 1, 1, 1, 1), "flow")],
)
def test_owner_starts_allocation(client, team_sizes, algorithm):
    """AC-1: доступное действие сохраняет коды работ, назначения и отметку о запуске."""
    assignment, works, teams = assignment_for_allocation(team_sizes)
    nonsubmitter = EnrollmentFactory(course=assignment.course).student
    client.force_login(assignment.course.owner)

    assert allocation_url(assignment).encode() in client.get(detail_url(assignment)).content
    response = client.post(allocation_url(assignment))
    assert response.status_code == 302

    run = AllocationRun.objects.get(assignment=assignment)
    assignment.refresh_from_db()
    assert assignment.allocated_at is not None
    assert assignment.phase == Phase.REVIEW
    assert run.created_at is not None
    assert run.k == 1
    assert run.algorithm == algorithm
    assert 0 <= run.seed < 2**63
    assigned = list(ReviewAssignment.objects.filter(run=run))
    assert Counter(row.submission_id for row in assigned) == {work.pk: 1 for work in works}
    authors = {
        author.pk: work.pk for work, team in zip(works, teams, strict=True) for author in team
    }
    assert {row.reviewer_id for row in assigned} <= authors.keys()
    assert nonsubmitter.pk not in {row.reviewer_id for row in assigned}
    pairs = {(authors[row.reviewer_id], row.submission_id) for row in assigned}
    assert all(a != b and (b, a) not in pairs for a, b in pairs)
    loads = Counter(row.reviewer_id for row in assigned)
    assert max(loads[author] for author in authors) - min(loads[author] for author in authors) <= 1
    assert allocation_url(assignment).encode() not in client.get(detail_url(assignment)).content


def test_generated_seed_reproduces_original_assignments(monkeypatch, caplog):
    """AC-6: секретный seed записан, используется в алгоритме и отсутствует в логах."""
    from secrets import randbits

    from apps.allocation import Work, allocate

    assignment, works, teams = assignment_for_allocation()
    seed_widths = []

    def fixed_seed(bits):
        seed_widths.append(bits)
        return SEED if bits == 63 else randbits(bits)

    monkeypatch.setattr("secrets.randbits", fixed_seed)
    with caplog.at_level("DEBUG", logger="apps.reviews"):
        run = services.run_allocation(assignment.course.owner, assignment.pk)
    assert 63 in seed_widths
    assert run.seed == SEED
    assert str(SEED) not in caplog.text
    source = [
        Work(str(work.public_code), frozenset(str(author.pk) for author in team))
        for work, team in zip(works, teams, strict=True)
    ]
    reviewers = [str(author.pk) for team in teams for author in team]
    expected = allocate(source, reviewers, 1, seed=SEED)
    actual = {
        str(row.submission.public_code): [str(row.reviewer_id)]
        for row in ReviewAssignment.objects.filter(run=run).select_related("submission")
    }
    assert actual == expected


def test_double_allocation_is_rejected_and_preserves_first_run():
    """AC-2: повторная попытка оставляет первый запуск и его назначения."""
    assignment, _, _ = assignment_for_allocation()
    owner = assignment.course.owner
    run = services.run_allocation(owner, assignment.pk)
    original = list(ReviewAssignment.objects.filter(run=run).order_by("pk").values())

    with pytest.raises(ValidationError):
        services.run_allocation(owner, assignment.pk)

    assert list(AllocationRun.objects.filter(assignment=assignment)) == [run]
    assert list(ReviewAssignment.objects.filter(run=run).order_by("pk").values()) == original


@pytest.mark.parametrize("deadline", ["submission", "review"])
def test_allocate_respects_deadline_boundaries(deadline):
    """AC-2: за секунду до закрытия сдачи и ровно в дедлайн рецензий запуска нет."""
    assignment, _, _ = assignment_for_allocation()
    when = (
        assignment.submission_deadline - timedelta(seconds=1)
        if deadline == "submission"
        else assignment.review_deadline
    )
    with freeze_time(when), pytest.raises(ValidationError):
        services.run_allocation(assignment.course.owner, assignment.pk)
    assert_nothing_allocated(assignment)


def test_allocate_at_submission_deadline_is_allowed():
    """AC-1: в момент дедлайна сдачи уже можно распределять."""
    assignment, _, _ = assignment_for_allocation()
    with freeze_time(assignment.submission_deadline):
        run = services.run_allocation(assignment.course.owner, assignment.pk)
    assert ReviewAssignment.objects.filter(run=run).count() == 5


@pytest.mark.parametrize(
    ("team_sizes", "rubric", "reason"),
    [((1, 1), True, "минимум"), ((1, 1, 1), False, "рубри")],
)
def test_owner_sees_unavailable_allocation_reason(client, team_sizes, rubric, reason):
    """AC-3: невыполнимость и отсутствие рубрики объясняются без записей в БД."""
    assignment, _, _ = assignment_for_allocation(team_sizes, rubric=rubric)
    client.force_login(assignment.course.owner)
    response = client.post(allocation_url(assignment), follow=True)

    assert response.status_code == 200
    assert reason in response.content.decode().casefold()
    assert_nothing_allocated(assignment)


def test_partial_write_rolls_back(monkeypatch):
    """AC-3: реальная запись назначения откатывается вместе с запуском при ошибке."""
    assignment, _, _ = assignment_for_allocation()
    from django.db.models import QuerySet

    bulk_create = QuerySet.bulk_create

    def fail_after_first(queryset, objects, *args, **kwargs):
        if queryset.model is ReviewAssignment:
            bulk_create(queryset, objects[:1], *args, **kwargs)
            raise IntegrityError("искусственная ошибка записи")
        return bulk_create(queryset, objects, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "bulk_create", fail_after_first)
    with pytest.raises((IntegrityError, ValidationError)):
        services.run_allocation(assignment.course.owner, assignment.pk)
    assert_nothing_allocated(assignment)


@pytest.fixture
def cycle():
    assignment, works, teams = assignment_for_allocation((2, 1, 1, 1, 1))
    run = AllocationRun.objects.create(assignment=assignment, seed=SEED, k=1, algorithm="flow")
    assignment.allocated_at = timezone.now()
    assignment.save(update_fields=["allocated_at"])
    assignments = [
        ReviewAssignment.objects.create(
            run=run, submission=works[(index + 1) % len(works)], reviewer=team[0]
        )
        for index, team in enumerate(teams)
    ]
    return assignment, works, teams, assignments


def test_owner_can_reassign_to_unused_coauthor(client, cycle):
    """AC-4: разрешённое переназначение переносит единственную нагрузку соавтору."""
    assignment, _, teams, assigned = cycle
    client.force_login(assignment.course.owner)
    url = reverse("reviews:reassign", args=[assignment.pk, assigned[0].pk])

    assert client.post(url, {"reviewer": teams[0][1].pk}).status_code == 302

    assigned[0].refresh_from_db()
    assert assigned[0].reviewer_id == teams[0][1].pk
    assert ReviewAssignment.objects.filter(run=assigned[0].run).count() == 5


@pytest.mark.parametrize(
    ("row_index", "team_index"),
    [
        pytest.param(0, 1, id="review-own-work"),
        pytest.param(4, 1, id="reciprocal-teams"),
        pytest.param(0, 4, id="unbalanced-load"),
        pytest.param(0, None, id="no-submission"),
    ],
)
def test_reassign_rejects_invalid_reviewer(cycle, row_index, team_index):
    """AC-4: каждая попытка нарушить инвариант оставляет назначения прежними."""
    assignment, _, teams, assigned = cycle
    row = assigned[row_index]
    candidate = (
        teams[team_index][0]
        if team_index is not None
        else EnrollmentFactory(course=assignment.course).student
    )
    old_reviewer = row.reviewer_id

    with pytest.raises(ValidationError):
        services.reassign_review(assignment.course.owner, assignment.pk, row.pk, candidate.pk)

    row.refresh_from_db()
    assert row.reviewer_id == old_reviewer


@pytest.mark.parametrize("same_student", [True, False])
def test_reassign_detects_duplicate_reviewer_and_team(same_student):
    """AC-4: второй рецензент той же команды или повтор студента недопустим."""
    assignment, works, teams = assignment_for_allocation((2, 1, 1, 1, 1), k=2)
    run = AllocationRun.objects.create(assignment=assignment, seed=SEED, k=2, algorithm="flow")
    assignment.allocated_at = timezone.now()
    assignment.save(update_fields=["allocated_at"])
    rows = {}
    for origin, team in enumerate(teams):
        for shift in (1, 2):
            destination = (origin + shift) % len(works)
            rows[(origin, destination)] = ReviewAssignment.objects.create(
                run=run, submission=works[destination], reviewer=team[(shift - 1) % len(team)]
            )
    chosen = rows[(1, 2)]
    with pytest.raises(ValidationError):
        services.reassign_review(
            assignment.course.owner, assignment.pk, chosen.pk, teams[0][int(not same_student)].pk
        )
    chosen.refresh_from_db()
    assert chosen.reviewer_id == teams[1][0].pk


def test_management_permissions_methods_and_csrf(cycle):
    """AC-2: действия владельца требуют POST и CSRF, другие роли не допускаются."""
    assignment, _, teams, assigned = cycle
    client = Client(enforce_csrf_checks=True)
    allocate = allocation_url(assignment)
    reassign = reverse("reviews:reassign", args=[assignment.pk, assigned[0].pk])
    manage = reverse("reviews:manage", args=[assignment.pk])

    assert client.get(manage).status_code == 302
    for actor in (teams[0][0], TeacherFactory()):
        client.force_login(actor)
        assert client.get(manage).status_code == 403
        assert client.get(allocate).status_code in (403, 405)
        assert client.get(reassign).status_code in (403, 405)

    client.force_login(assignment.course.owner)
    assert client.get(manage).status_code == 200
    assert client.get(allocate).status_code == 405
    assert client.get(reassign).status_code == 405
    assert client.post(allocate).status_code == 403
    assert client.post(reassign, {"reviewer": teams[0][1].pk}).status_code == 403


def test_reassign_rejects_row_from_another_assignment(client, cycle):
    """AC-2, AC-4: идентификатор чужого задания нельзя подставить в запрос."""
    assignment, _, _, rows = cycle
    other = AssignmentFactory(course=assignment.course)
    client.force_login(assignment.course.owner)
    url = reverse("reviews:reassign", args=[other.pk, rows[0].pk])

    assert client.post(url, {"reviewer": rows[0].reviewer_id}).status_code == 404


def test_teacher_sees_closed_run_but_cannot_reassign(client, cycle):
    """AC-4: просмотр остаётся после закрытия, изменение запрещено на границе."""
    assignment, works, teams, rows = cycle
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline):
        page = client.get(reverse("reviews:manage", args=[assignment.pk]))
        assert page.status_code == 200
        assert str(works[1].public_code).encode() in page.content
        with pytest.raises(ValidationError):
            services.reassign_review(
                assignment.course.owner, assignment.pk, rows[0].pk, teams[0][1].pk
            )


def test_student_sees_only_owned_public_assignment_codes(client, cycle):
    """AC-5, AC-6: HTML и DTO не раскрывают авторов, внутренние ID, seed и чужие коды."""
    assignment, works, teams, rows = cycle
    reviewer = teams[0][0]
    target_author = teams[1][0]
    expected_code = works[1].public_code
    client.force_login(reviewer)

    assert services.student_work_codes(reviewer, assignment.pk) == (expected_code,)
    page = client.get(detail_url(assignment))
    assert page.status_code == 200
    html = page.content.decode()
    assert str(expected_code) in html
    for value in (
        target_author.username,
        target_author.email,
        str(SEED),
        works[1].file_key,
        reverse("reviews:reassign", args=[assignment.pk, rows[0].pk]),
        reverse("reviews:manage", args=[assignment.pk]),
        *(str(work.public_code) for work in works if work.public_code != expected_code),
    ):
        assert value not in html
    assert services.student_work_codes(teams[0][1], assignment.pk) == ()
    client.force_login(teams[0][1])
    assert str(expected_code).encode() not in client.get(detail_url(assignment)).content


@pytest.mark.django_db(transaction=True)
def test_concurrent_start_saves_exactly_one_run():
    """AC-2: два независимых соединения сохраняют один запуск и полный комплект."""
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connections

    if connection.vendor == "sqlite" and connection.creation.is_in_memory_db(
        connection.settings_dict["NAME"]
    ):
        pytest.skip("SQLite в памяти не ждёт конкурирующую блокировку записи.")

    assignment, works, _ = assignment_for_allocation()
    owner = assignment.course.owner
    barrier = Barrier(2, timeout=10)

    def start():
        close_old_connections()
        try:
            barrier.wait()
            services.run_allocation(owner, assignment.pk)
        except ValidationError:
            return False
        else:
            return True
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        assert sorted(future.result(timeout=20) for future in futures) == [False, True]
    run = AllocationRun.objects.get(assignment=assignment)
    assert ReviewAssignment.objects.filter(run=run).count() == len(works)


def test_failed_allocation_reason_is_scoped_to_owner_and_assignment(client, monkeypatch):
    """AC-3, AC-5: непрочитанная причина не появляется на другом экране или после входа студента."""
    from apps.allocation import InfeasibleAllocation

    assignment, works, teams = assignment_for_allocation()
    other = AssignmentFactory(course=assignment.course)
    marker = str(works[0].public_code).encode()

    def cannot_allocate(*args, **kwargs):
        raise InfeasibleAllocation(f"Не хватает рецензентов для {works[0].public_code}.")

    monkeypatch.setattr(services, "allocate", cannot_allocate)
    client.force_login(assignment.course.owner)

    assert client.post(allocation_url(assignment)).status_code == 302
    assert marker not in client.get(detail_url(other)).content
    assert marker in client.get(detail_url(assignment)).content
    assert marker not in client.get(detail_url(assignment)).content

    assert client.post(allocation_url(assignment)).status_code == 302
    client.force_login(teams[0][0])
    assert marker not in client.get(detail_url(assignment)).content
