"""Тесты харнесса агента: хуки .claude/hooks ведут себя так, как описано в docs/WORKFLOW.md.

Каждый тест запускает настоящий скрипт хука на временном git-репозитории
(CLAUDE_PROJECT_DIR = tmp), подавая JSON события на stdin, как это делает Claude Code.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
BLOCK = 2


@pytest.fixture
def project(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / ".claude" / ".state").mkdir(parents=True)
    migration = tmp_path / "apps" / "x" / "migrations" / "0001_initial.py"
    migration.parent.mkdir(parents=True)
    migration.write_text("# applied\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def run_hook(project: Path, hook: str, event: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(event),
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        text=True,
        check=False,
    )


def edit(project: Path, rel_path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(project / rel_path)}}


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def set_flag(project: Path, name: str) -> None:
    (project / ".claude" / ".state" / name).touch()


# ---------------------------------------------------------------- guard_files


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", BLOCK),
        (".env.local", BLOCK),
        (".env.example", 0),
        ("apps/core/views.py", 0),
        ("apps/x/migrations/0001_initial.py", BLOCK),  # закоммиченная миграция
        ("apps/x/migrations/0002_new.py", 0),  # новая — можно
        (".claude/settings.json", BLOCK),
        (".claude/hooks/stop_check.py", BLOCK),
        (".claude/agents/implementer.md", 0),
        ("tests/unit/test_smoke.py", 0),
    ],
)
def test_guard_files(project, path, expected):
    assert run_hook(project, "guard_files.py", edit(project, path)).returncode == expected


def test_guard_files_protect_tests_mode(project):
    set_flag(project, "protect-tests")
    result = run_hook(project, "guard_files.py", edit(project, "tests/unit/test_x.py"))
    assert result.returncode == BLOCK
    assert "protect-tests" in result.stderr
    assert run_hook(project, "guard_files.py", edit(project, "apps/a.py")).returncode == 0


def test_guard_files_harness_unlock_by_human(project):
    set_flag(project, "harness-unlock")
    event = edit(project, ".claude/settings.json")
    assert run_hook(project, "guard_files.py", event).returncode == 0


# ---------------------------------------------------------------- guard_bash


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("make check", 0),
        ("uv run pytest tests/unit -q", 0),
        ("git commit -m x --no-verify", BLOCK),
        ("git push --force origin feat/x", BLOCK),
        ("git push -f origin feat/x", BLOCK),
        ("git reset --hard HEAD~1", BLOCK),
        ("uv run pytest --cov-fail-under=0", BLOCK),
        ("uv run pytest --no-cov", BLOCK),
        ("cat .env", BLOCK),
        ("cat .env.example", 0),
        ("touch .claude/.state/harness-unlock", BLOCK),
        ("git commit -m 'feat: x'", BLOCK),  # фикстура на ветке main
    ],
)
def test_guard_bash(project, command, expected):
    assert run_hook(project, "guard_bash.py", bash(command)).returncode == expected


def test_guard_bash_allows_commit_on_feature_branch(project):
    subprocess.run(["git", "switch", "-q", "-c", "feat/T-001-x"], cwd=project, check=True)
    assert run_hook(project, "guard_bash.py", bash("git commit -m x")).returncode == 0


def test_guard_bash_protect_tests_blocks_shell_edits(project):
    set_flag(project, "protect-tests")
    event = bash("sed -i 's/1/2/' tests/unit/test_x.py")
    assert run_hook(project, "guard_bash.py", event).returncode == BLOCK
    assert run_hook(project, "guard_bash.py", bash("uv run pytest tests/")).returncode == 0


# ---------------------------------------------------------------- session_start / stop


def test_session_start_gives_context(project):
    (project / "docs").mkdir()
    (project / "docs" / "PROGRESS.md").write_text("## последняя запись\n")
    set_flag(project, "protect-tests")
    result = run_hook(project, "session_start.py", {})
    assert result.returncode == 0
    assert "Ветка: `main`" in result.stdout
    assert "последняя запись" in result.stdout
    assert "protect-tests" in result.stdout


def test_stop_skips_checks_without_code_changes(project):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        cwd=project,
        check=True,
    )
    assert run_hook(project, "stop_check.py", {"stop_hook_active": False}).returncode == 0


def test_stop_releases_after_max_retries(project):
    (project / "app.py").write_text("x = 1\n")  # есть изменения кода
    (project / ".claude" / ".state" / "stop-retries").write_text("3")
    result = run_hook(project, "stop_check.py", {"stop_hook_active": True})
    assert result.returncode == 0  # предохранитель от бесконечного цикла
