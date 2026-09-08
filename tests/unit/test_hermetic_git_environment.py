"""The suite must not be able to see the developer's git identity (Plan 00252 A).

Seven tests across Plans 00245 and 00248 took their git premise from ambient
configuration — a global ``user.name``/``user.email`` on the developer's machine
that a CI runner does not have — and so went red on a fresh runner and green
locally. Each was fixed by hand; nothing stopped the eighth. The guard in
``tests/conftest.py`` (``hermetic_git_environment``) removes the premise from
every test process instead, and this file is that guard's own test: it asserts
what a test can observe of git's ambient configuration, which must be nothing.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - trusted system tool (git) for repo fixtures
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.conftest import (
    HERMETIC_GIT_EMAIL,
    HERMETIC_GIT_NAME,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.GIT_COMMIT,
    )


class TestGlobalAndSystemConfigAreEmpty:
    def test_global_config_is_an_empty_file_under_a_temp_dir(self, tmp_path: Path) -> None:
        global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
        assert global_config.is_file()
        assert global_config.read_text(encoding="utf-8") == ""
        assert not global_config.is_relative_to(Path.home())
        assert _git(tmp_path, "config", "--global", "--list").stdout == ""

    def test_system_config_is_not_consulted(self, tmp_path: Path) -> None:
        assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
        system_config = Path(os.environ["GIT_CONFIG_SYSTEM"])
        assert system_config.is_file()
        assert system_config.read_text(encoding="utf-8") == ""
        assert _git(tmp_path, "config", "--system", "--list").stdout == ""


class TestDeveloperIdentityIsInvisible:
    """``user.name`` is what the seven failures read; it must resolve to nothing."""

    def test_no_user_name_outside_a_repo(self, tmp_path: Path) -> None:
        result = _git(tmp_path, "config", "--get", "user.name")
        assert result.returncode == 1, result.stderr
        assert result.stdout == ""

    def test_no_user_name_or_email_in_a_fresh_repo(self, tmp_path: Path) -> None:
        assert _git(tmp_path, "init", "-q").returncode == 0
        for key in ("user.name", "user.email"):
            result = _git(tmp_path, "config", "--get", key)
            assert result.returncode == 1, (key, result.stderr)
            assert result.stdout == ""

    def test_home_gitconfig_is_not_what_git_reads(self, tmp_path: Path) -> None:
        # ``--show-origin`` names the file each value came from; nothing may
        # come from anywhere under HOME, whatever the developer keeps there.
        result = _git(tmp_path, "config", "--list", "--show-origin")
        home = str(Path.home())
        origins = [line.split("\t", 1)[0] for line in result.stdout.splitlines()]
        assert not [o for o in origins if o.startswith(f"file:{home}")], origins


class TestFixedIdentityIsSupplied:
    """Neutralising the premise must not replace one silent dependency with a crash.

    ``tmp_git_repo`` and the hand-rolled helpers all set a local identity, but
    the guard's job is to make the environment agree with CI, and a CI runner
    with no identity at all cannot commit. The fixed identity is pinned as
    ``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` so every process agrees on it.
    """

    def test_env_carries_the_fixed_identity(self) -> None:
        assert os.environ["GIT_AUTHOR_NAME"] == HERMETIC_GIT_NAME
        assert os.environ["GIT_AUTHOR_EMAIL"] == HERMETIC_GIT_EMAIL
        assert os.environ["GIT_COMMITTER_NAME"] == HERMETIC_GIT_NAME
        assert os.environ["GIT_COMMITTER_EMAIL"] == HERMETIC_GIT_EMAIL

    def test_commit_in_fresh_repo_is_authored_by_the_fixed_identity(self, tmp_path: Path) -> None:
        assert _git(tmp_path, "init", "-q").returncode == 0
        (tmp_path / "f.txt").write_text("x\n", encoding="utf-8")
        assert _git(tmp_path, "add", "f.txt").returncode == 0
        commit = _git(tmp_path, "commit", "-q", "-m", "init")
        assert commit.returncode == 0, commit.stderr
        shown = _git(tmp_path, "log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout.strip()
        ident = f"{HERMETIC_GIT_NAME} <{HERMETIC_GIT_EMAIL}>"
        assert shown == f"{ident}|{ident}"

    def test_ambient_dates_are_not_inherited(self) -> None:
        assert "GIT_AUTHOR_DATE" not in os.environ
        assert "GIT_COMMITTER_DATE" not in os.environ
