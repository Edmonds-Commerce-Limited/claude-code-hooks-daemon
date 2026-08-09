"""Every leak surface has BOTH a write-time guard and a batch guard (Plan 00202).

This is the anti-regression artifact for the whole sensitive-content effort.
Its input is not a wish list — it is the measured set of surfaces that cleaning
this repository's own history actually had to touch. ``--replace-text`` rewrites
blob contents and nothing else, so four distinct ``git-filter-repo`` mechanisms
plus two manual steps were needed:

======================  ============================  ===================
Surface                 Rewrite mechanism             First guarded by
======================  ============================  ===================
File contents           ``--replace-text``            Plan 00201
File paths              ``--path-rename``             ``fb91d81f``
Commit messages         ``--replace-message``         Plan 00202 Phase 1
Author/committer id     ``--mailmap``                 Plan 00202 Phase 1
Tag names               manual re-tag                 Plan 00202 Phase 1
Tag messages            manual re-tag                 Plan 00202 Phase 1
Branch names            manual rename                 Plan 00202 Phase 1
======================  ============================  ===================

Each surface needs TWO guards, not one. A PreToolUse handler cannot see what is
already committed, and a batch scanner cannot stop the next write — so a
surface with only one of them is half-covered, which is the state every one of
these was in until this plan.

The tests EXERCISE each cell rather than asserting a list of names: a
declaration of coverage is exactly the kind of thing that stays green while the
thing it describes rots. Adding an eighth surface means adding a row here, and
the row does not pass until a real guard actually catches it.
"""

import json
import subprocess  # nosec B404 - subprocess used for git fixtures and QA checkers
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TREE_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_sensitive_content.py"
_HISTORY_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_git_history.py"
_TREE_JSON = _REPO_ROOT / "untracked" / "qa" / "sensitive_content.json"
_HISTORY_JSON = _REPO_ROOT / "untracked" / "qa" / "git_history.json"

_TERM = "zzqx-nonsense-term"

# One row per surface. `bash_command` is None for the two surfaces that arrive
# as a file write rather than a git invocation.
_GIT_SURFACES: tuple[tuple[str, str, str], ...] = (
    ("commit-message", f'git commit -m "fixes {_TERM}"', "commit-message"),
    ("author-identity", f'git config user.name "{_TERM}"', "commit-identity"),
    ("tag-name", f"git tag {_TERM}-v1", "ref-name"),
    ("tag-message", f'git tag -a v1.0.0 -m "ships {_TERM}"', "tag-message"),
    ("branch-name", f"git checkout -b {_TERM}-work", "ref-name"),
)


@pytest.fixture(autouse=True)
def _reset_redaction_caches() -> None:
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


def _handler(secret_file: Path) -> SensitiveContentHandler:
    handler = SensitiveContentHandler()
    handler._secret_word_list_path = str(secret_file)
    return handler


def _secret_list(root: Path) -> Path:
    secret_file = root / ".claude" / "block-words.secret"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(f"{_TERM}\n")
    return secret_file


def _write_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "handlers:\n"
        "  pre_tool_use:\n"
        "    sensitive_content:\n"
        "      enabled: true\n"
        "      options:\n"
        "        public_patterns: []\n"
    )


def _git(repo: Path, *args: str, **env: str) -> None:
    environment = {
        "GIT_AUTHOR_NAME": "Clean Author",
        "GIT_AUTHOR_EMAIL": "clean@example.com",
        "GIT_COMMITTER_NAME": "Clean Author",
        "GIT_COMMITTER_EMAIL": "clean@example.com",
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo),
        **env,
    }
    subprocess.run(  # nosec B603 B607 - trusted system tool (git), list form
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _run(checker: Path, output: Path, *args: str) -> dict[str, Any]:
    subprocess.run(  # nosec B603 - trusted first-party checker script
        [sys.executable, str(checker), "--json", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert output.exists(), f"Expected JSON output at {output}"
    return json.loads(output.read_text())


class TestWriteTimeGuardCoversEverySurface:
    """Nothing carrying a term may ENTER the repository through any surface."""

    def test_file_content(self, tmp_path: Path) -> None:
        handler = _handler(_secret_list(tmp_path))
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "clean.md"), "content": f"has {_TERM}\n"},
        }
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_file_path(self, tmp_path: Path) -> None:
        handler = _handler(_secret_list(tmp_path))
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / f"{_TERM}-notes.md"),
                "content": "wholly innocent body\n",
            },
        }
        # The path is matched RELATIVE to the project root — checking the
        # absolute path would deny every write in a checkout that merely lives
        # under a listed directory. So the root must be the fixture's own root,
        # or there is no relative portion left to match.
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content."
            "resolve_project_root",
            return_value=str(tmp_path),
        ):
            assert handler.matches(hook_input) is True
            assert handler.handle(hook_input).decision == Decision.DENY

    @pytest.mark.parametrize(
        ("surface", "command"),
        [(surface, command) for surface, command, _ in _GIT_SURFACES],
    )
    def test_git_metadata_surface(self, tmp_path: Path, surface: str, command: str) -> None:
        handler = _handler(_secret_list(tmp_path))
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is True, f"{surface} is unguarded at write time"
        assert handler.handle(hook_input).decision == Decision.DENY


class TestBatchGuardCoversEverySurface:
    """Whatever already landed must still be FOUND — a write-time guard is blind to it."""

    def test_file_content(self, tmp_path: Path) -> None:
        _secret_list(tmp_path)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "clean.md").write_text(f"has {_TERM}\n")

        data = _run(_TREE_CHECKER, _TREE_JSON, "--path", str(tmp_path), "--config", str(config))

        assert data["summary"]["passed"] is False

    def test_file_path(self, tmp_path: Path) -> None:
        _secret_list(tmp_path)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / f"{_TERM}-notes.md").write_text("wholly innocent body\n")

        data = _run(_TREE_CHECKER, _TREE_JSON, "--path", str(tmp_path), "--config", str(config))

        assert data["summary"]["passed"] is False

    @pytest.mark.parametrize(
        ("surface", "expected"),
        [(surface, expected) for surface, _, expected in _GIT_SURFACES],
    )
    def test_git_metadata_surface(self, tmp_path: Path, surface: str, expected: str) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "file.txt").write_text("clean body\n")
        _git(repo, "add", "file.txt")
        _git(repo, "commit", "-q", "-m", "an ordinary first commit")
        _secret_list(repo)
        _contaminate(repo, surface)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run(_HISTORY_CHECKER, _HISTORY_JSON, "--repo", str(repo), "--config", str(config))

        assert expected in {
            v["surface"] for v in data["violations"]
        }, f"{surface} is unguarded in committed history"


def _contaminate(repo: Path, surface: str) -> None:
    """Put the term on exactly ONE surface of an otherwise clean fixture repo."""
    if surface == "commit-message":
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"fixes {_TERM}")
    elif surface == "author-identity":
        _git(
            repo,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "an ordinary message",
            GIT_AUTHOR_NAME=_TERM,
            GIT_AUTHOR_EMAIL=f"{_TERM}@example.com",
            GIT_COMMITTER_NAME="Clean Author",
            GIT_COMMITTER_EMAIL="clean@example.com",
        )
    elif surface == "tag-name":
        _git(repo, "tag", f"{_TERM}-v1")
    elif surface == "tag-message":
        _git(repo, "tag", "-a", "v1.0.0", "-m", f"ships {_TERM}")
    elif surface == "branch-name":
        _git(repo, "branch", f"{_TERM}-work")
    else:  # pragma: no cover - a new surface with no fixture must fail loudly
        raise AssertionError(
            f"No contamination fixture for surface '{surface}'. A surface added to "
            "_GIT_SURFACES without one would otherwise pass by doing nothing."
        )


class TestTheSurfaceListItselfIsHonest:
    def test_every_git_surface_has_a_contamination_fixture(self, tmp_path: Path) -> None:
        """A row with no fixture must raise, never silently pass.

        Without this, adding a surface to ``_GIT_SURFACES`` and forgetting the
        fixture would produce a test that contaminates nothing, finds nothing
        it was not looking for, and reports coverage that does not exist.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "file.txt").write_text("clean body\n")
        _git(repo, "add", "file.txt")
        _git(repo, "commit", "-q", "-m", "an ordinary first commit")

        with pytest.raises(AssertionError, match="No contamination fixture"):
            _contaminate(repo, "a-surface-nobody-wrote-a-fixture-for")

    def test_all_seven_surfaces_are_represented(self) -> None:
        """Two file surfaces are covered by explicit tests; five are parametrised."""
        assert len(_GIT_SURFACES) == 5
        assert len({surface for surface, _, _ in _GIT_SURFACES}) == 5
