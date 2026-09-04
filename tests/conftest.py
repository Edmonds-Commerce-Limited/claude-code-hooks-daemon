"""Pytest configuration and shared fixtures for hooks daemon tests.

This module provides test fixtures and utilities used across all test files.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.core.response_schemas import (
    get_response_schema,
    is_valid_response,
    validate_response,
)


@pytest.fixture
def response_validator():
    """Fixture providing response validation utilities.

    Usage:
        def test_handler_response(response_validator):
            response = {"hookSpecificOutput": {...}}
            response_validator.assert_valid("PreToolUse", response)
    """

    class ResponseValidator:
        """Helper class for validating hook responses in tests."""

        @staticmethod
        def assert_valid(event_name: str, response: dict[str, Any]) -> None:
            """Assert that a response is valid for the given event.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Raises:
                AssertionError: If response is invalid
            """
            errors = validate_response(event_name, response)
            if errors:
                error_msg = f"Invalid {event_name} response:\n" + "\n".join(
                    f"  - {err}" for err in errors
                )
                raise AssertionError(error_msg)

        @staticmethod
        def assert_invalid(event_name: str, response: dict[str, Any]) -> None:
            """Assert that a response is INVALID for the given event.

            Useful for testing that validation catches bad responses.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Raises:
                AssertionError: If response is unexpectedly valid
            """
            if is_valid_response(event_name, response):
                raise AssertionError(
                    f"Expected invalid {event_name} response, but validation passed"
                )

        @staticmethod
        def get_errors(event_name: str, response: dict[str, Any]) -> list[str]:
            """Get validation errors for a response.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Returns:
                List of validation error messages
            """
            return validate_response(event_name, response)

        @staticmethod
        def get_schema(event_name: str) -> dict[str, Any]:
            """Get the JSON schema for an event.

            Args:
                event_name: Hook event name

            Returns:
                JSON schema dictionary
            """
            return get_response_schema(event_name)

    return ResponseValidator()


@pytest.fixture
def hook_result_validator(response_validator):
    """Fixture for validating HookResult.to_json() output.

    Usage:
        def test_hook_result(hook_result_validator):
            result = HookResult(decision=Decision.DENY, reason="Test")
            hook_result_validator.assert_valid("PreToolUse", result)
    """

    class HookResultValidator:
        """Helper class for validating HookResult instances."""

        def __init__(self, response_validator):
            self.response_validator = response_validator

        def assert_valid(self, event_name: str, hook_result) -> None:
            """Assert that a HookResult produces valid JSON for the event.

            Args:
                event_name: Hook event name
                hook_result: HookResult instance

            Raises:
                AssertionError: If response is invalid
            """
            response = hook_result.to_json(event_name)
            self.response_validator.assert_valid(event_name, response)

        def get_errors(self, event_name: str, hook_result) -> list[str]:
            """Get validation errors for a HookResult's JSON output.

            Args:
                event_name: Hook event name
                hook_result: HookResult instance

            Returns:
                List of validation error messages
            """
            response = hook_result.to_json(event_name)
            return self.response_validator.get_errors(event_name, response)

    return HookResultValidator(response_validator)


class GitIndexWatch:
    """Assert whether a block of code made git rewrite ``.git/index`` (Plan 00246).

    Rewriting the index means the command took ``.git/index.lock``. The daemon
    shares a working tree with the agent, so a lock it takes is a lock the agent
    can collide with — and `git status` takes one unless told otherwise, which is
    how a pure read ends up contending.

    The trap this exists to close: if the index is already up to date, git skips
    the refresh of its own accord and "was not rewritten" is true of ANY
    implementation — the assertion passes while proving nothing. Both context
    managers below make the cached stat info stale first, so a test cannot
    silently become vacuous. Pair every ``expect_none`` with an ``expect_one``
    control on bare git.
    """

    @staticmethod
    def _identity(repo: Path) -> tuple[int, int]:
        """Inode + mtime of ``.git/index``, which changes iff git rewrote it.

        A repo with no index yet has nothing to watch, and a bare
        ``FileNotFoundError`` from a fixture helper reads as a bug in the test
        rather than a mis-set-up repo — so say which is which.
        """
        index = repo / ".git" / "index"
        if not index.exists():
            raise AssertionError(
                f"{repo} has no .git/index, so there is no index rewrite to "
                f"observe. Commit something first — an empty repo makes every "
                f"assertion here vacuous."
            )
        stat = index.stat()
        return (stat.st_ino, stat.st_mtime_ns)

    @staticmethod
    def _make_stale(repo: Path) -> None:
        """Touch every TRACKED file so git wants to refresh the index next read.

        Driven by ``git ls-files`` rather than by listing the directory (Plan
        00248 F6). The first version iterated ``repo.iterdir()`` non-recursively
        and touched whatever files it found without checking they were tracked —
        so for any repo whose tracked files live in subdirectories it touched
        NOTHING, git had no refresh to skip, and ``expect_none`` passed while
        proving nothing. That is precisely the vacuity this class exists to
        prevent, reintroduced one directory deep, and it would have surfaced the
        first time someone used the fixture with a realistic tree.
        """
        import subprocess  # nosec B404 - runs the trusted system `git` only

        listing = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        ).stdout
        tracked = [name for name in listing.split("\0") if name]
        if not tracked:
            raise AssertionError(
                f"{repo} has no tracked files, so the index cannot be made "
                f"stale and any 'was not rewritten' assertion is vacuous."
            )
        for name in tracked:
            path = repo / name
            if path.is_file():
                path.touch()

    @contextmanager
    def expect_none(self, repo: Path, what: str) -> Generator[None, None, None]:
        """Assert the enclosed block did NOT make git rewrite the index."""
        self._make_stale(repo)
        before = self._identity(repo)
        yield
        assert self._identity(repo) == before, (
            f"{what} rewrote .git/index, so it took .git/index.lock and can "
            f"collide with the agent's own git commands in the same tree"
        )

    @contextmanager
    def expect_one(self, repo: Path, what: str) -> Generator[None, None, None]:
        """Assert the enclosed block DID rewrite the index — the control.

        Proves the scenario genuinely provokes a refresh, without which a
        sibling ``expect_none`` assertion would pass vacuously.
        """
        self._make_stale(repo)
        before = self._identity(repo)
        yield
        assert self._identity(repo) != before, (
            f"{what} did not provoke an index refresh, so any sibling "
            f"'takes no lock' assertion passes vacuously — fix the fixture"
        )


@pytest.fixture
def git_index_watch() -> GitIndexWatch:
    """Watch whether code under test takes git's index lock. See GitIndexWatch."""
    return GitIndexWatch()


def layout_declaring_vendor_dirs(*names: str) -> ProjectLayout:
    """A `ProjectLayout` whose `vendor_dirs` is the canonical set plus `names`.

    Shared because several handlers need the same "a project declared this
    directory vendored" setup (Plan 00331), and each was otherwise going to
    grow its own copy of an eight-field construction.

    Additive, matching `layout:`'s default `mode` -- so a test using it also
    proves the built-ins were not displaced, which is the failure a
    replace-shaped helper would hide.
    """
    return ProjectLayout(
        source_dirs=(),
        test_dirs=("tests",),
        config_dirs=("config",),
        vendor_dirs=frozenset(CORE_VENDORED_BUILD_DIR_NAMES | set(names)),
        agent_docs_dir="CLAUDE",
        human_docs_dir="docs",
        plan_dir="CLAUDE/Plan",
        plan_archive_dirs=("Completed",),
    )


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with an identity and one committed file.

    Paired with :class:`GitIndexWatch`: proving that code does or does not take
    the index lock needs a REAL repo with a real index, which a mocked
    ``subprocess`` cannot provide.

    Every git call is BOUNDED and every ambient influence is neutralised (Plan
    00248). The local identity is set, but identity is not the only thing git
    reads from the environment: a developer with ``commit.gpgsign=true`` globally
    would have this fixture block on a signing prompt, and an unbounded
    ``check=True`` commit turns that into a hung suite in a file that has nothing
    to do with signing. This is the same defect class as Plan 00245's CI
    failures — a test taking its premise from the environment instead of stating
    it — so the premise is stated here.
    """
    import subprocess  # nosec B404 - runs the trusted system `git` only

    repo = tmp_path / "repo"
    repo.mkdir()
    commands = (
        ["git", "init"],
        ["git", "config", "--local", "user.email", "t@t"],
        ["git", "config", "--local", "user.name", "t"],
        ["git", "config", "--local", "commit.gpgsign", "false"],
        ["git", "config", "--local", "tag.gpgsign", "false"],
    )
    for command in commands:
        subprocess.run(  # nosec B603
            command, cwd=repo, capture_output=True, check=True, timeout=Timeout.GIT_CONTEXT
        )
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(  # nosec B603
        ["git", "add", "tracked.txt"],
        cwd=repo,
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    subprocess.run(  # nosec B603
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_COMMIT,
    )
    return repo


#: Runtime-path overrides that take precedence over every computed daemon path
#: (see CLAUDE.md, "Environment Overrides"). Because they win unconditionally,
#: a developer or CI runner that happens to export one silently changes what
#: the path-generation tests compute.
_DAEMON_PATH_OVERRIDE_VARS = (
    "CLAUDE_HOOKS_SOCKET_PATH",
    "CLAUDE_HOOKS_PID_PATH",
    "CLAUDE_HOOKS_LOG_PATH",
)


@pytest.fixture(autouse=True)
def isolate_daemon_path_overrides(monkeypatch):
    """Unset the daemon path-override env vars for every test.

    These three variables override the computed socket/PID/log paths, so a
    shell that exports any of them makes 17 tests in ``tests/daemon/test_paths.py``
    fail with assertions about a path the test never chose. That is an
    environment leak, not a defect in the code under test — and it would be
    diagnosed as CI flake precisely because it depends on who is running it.

    Tests that WANT an override still set it explicitly (``patch.dict`` /
    ``monkeypatch.setenv``); this only removes ambient values, so it cannot
    mask a test's own intent.
    """
    for var in _DAEMON_PATH_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)


#: Tracked files at the repository root that NO test may write. A test that
#: rewrites one of these is editing the developer's working tree from inside
#: the suite: it can be committed by accident, it makes an unrelated later run
#: look dirty, and — because the damage is a plausible-looking regeneration
#: rather than a crash — nothing about it reads as a failure.
_TRACKED_FILES_NO_TEST_MAY_WRITE = ("CLAUDE.md", ".claude/HOOKS-DAEMON.md")

_REPO_ROOT = Path(__file__).resolve().parents[1]


#: Where content is preserved before the guard overwrites it. Gitignored, so it
#: never reaches a commit. A diagnostic must not be the only copy of the work it
#: is about to discard.
_REJECTED_WRITE_DIR_PARTS = ("untracked", "rejected-writes")

#: Suffix for a preserved copy, so it never looks like a source file.
_REJECTED_WRITE_SUFFIX = ".rejected"


def _tracked_file_fingerprints() -> dict[str, tuple[int, int]]:
    """Cheap (size, mtime_ns) per protected file. One stat each, per test."""
    fingerprints: dict[str, tuple[int, int]] = {}
    for relative in _TRACKED_FILES_NO_TEST_MAY_WRITE:
        path = _REPO_ROOT / relative
        try:
            stat = path.stat()
        except OSError:
            continue
        fingerprints[relative] = (stat.st_size, stat.st_mtime_ns)
    return fingerprints


def _tracked_file_bytes() -> dict[str, bytes]:
    """Byte baseline for the protected files, captured PER TEST.

    Per test, deliberately. A session-scoped baseline restores the file to what
    it held when pytest STARTED, which silently reverts every edit a developer
    or agent made while the suite ran — the suite runs for minutes, and an edit
    landing anywhere in that span is attributed to whichever test happened to be
    executing. Capturing at test setup shrinks that window from the whole
    session to one test.

    The files are small and already in page cache, so the extra read per test is
    not measurable against a suite that runs thousands of them.
    """
    captured: dict[str, bytes] = {}
    for relative in _TRACKED_FILES_NO_TEST_MAY_WRITE:
        try:
            captured[relative] = (_REPO_ROOT / relative).read_bytes()
        except OSError:
            continue
    return captured


def _preserve_rejected_write(
    relative: str, path: Path, target_dir: Path | None = None
) -> Path | None:
    """Copy what is about to be overwritten somewhere recoverable.

    Even with a per-test baseline the guard cannot distinguish a test's write
    from an external edit that landed inside the same window — it sees only that
    the bytes changed. So it must never be the sole copy: whatever it is about
    to discard is written out first, and the failure message names the file.

    Returns:
        The preserved path, or None when there was nothing to preserve. Never
        raises: this runs in a fixture teardown, where an exception would
        replace a useful assertion failure with an unrelated one.
    """
    destination_dir = (
        target_dir if target_dir is not None else _REPO_ROOT.joinpath(*_REJECTED_WRITE_DIR_PARTS)
    )
    try:
        content = path.read_bytes()
    except OSError:
        return None
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        preserved = destination_dir / (relative.replace("/", "_") + _REJECTED_WRITE_SUFFIX)
        preserved.write_bytes(content)
    except OSError:
        return None
    return preserved


@pytest.fixture(autouse=True)
def no_test_writes_tracked_generated_docs():
    """Fail the test that rewrites a tracked generated doc, and undo it.

    ``DaemonController.initialise()`` runs ``ClaudeMdInjector`` as a SIDE
    EFFECT, so any test that initialises a controller with the real repository
    as ``workspace_root`` silently rewrites this repo's ``CLAUDE.md`` — and
    with a handler set built from whatever that test happened to configure. A
    test that omits ``pseudo_events_config`` therefore DELETES every
    pseudo-event handler's guidance from the developer's tracked file, passes
    green, and leaves a 42-line deletion staged for whoever commits next. The
    injector even auto-commits.

    That went unnoticed twice: the file still looks like a normal
    regeneration, the daemon reports healthy, and the only surface that
    objects is an unrelated coverage test on a LATER run — by which point the
    cause looks like the daemon rather than the suite.

    A stat per protected file per test is the cost of never diagnosing that
    from scratch again. Tests that legitimately exercise the injector point it
    at ``tmp_path``; nothing has a reason to write the real files.

    The baseline is captured HERE, per test, and never session-wide. A
    session-scoped baseline restores the file to what it held when pytest
    started, so an edit made by a developer or agent minutes into the run is
    reverted wholesale — which is exactly what happened, twice, to a hand edit
    made while this suite was running. The window cannot be closed entirely
    (this fixture still cannot distinguish a test's write from an external edit
    inside the same test), so whatever is about to be overwritten is preserved
    first and named in the failure. A diagnostic must never be the only copy of
    the work it discards.
    """
    baseline = _tracked_file_bytes()
    before = _tracked_file_fingerprints()
    yield
    after = _tracked_file_fingerprints()

    mutated = [name for name, fingerprint in after.items() if before.get(name) != fingerprint]
    if not mutated:
        return

    # Preserve first, restore second. The guard cannot tell a test's write from
    # an external edit that landed in the same window, so it must never be the
    # only copy of what it discards.
    restored = []
    preserved_paths = []
    for name in mutated:
        original = baseline.get(name)
        if original is None:
            continue
        preserved = _preserve_rejected_write(name, _REPO_ROOT / name)
        if preserved is not None:
            preserved_paths.append(str(preserved))
        (_REPO_ROOT / name).write_bytes(original)
        restored.append(name)

    raise AssertionError(
        "This test rewrote tracked generated doc(s): "
        + ", ".join(mutated)
        + ". Almost always this is DaemonController.initialise() being called "
        "with workspace_root pointing at the real repository — initialise() "
        "runs ClaudeMdInjector as a side effect and will rewrite CLAUDE.md "
        "with whatever handler set the test configured, deleting the guidance "
        "of every handler it did not wire up. Point workspace_root at "
        "tmp_path, or patch ClaudeMdInjector.inject for the duration if the "
        "test genuinely needs this project's own config. "
        "IF NO TEST TOUCHES THESE FILES, suspect an EXTERNAL edit: an editor or "
        "agent that modified a protected file while the suite was running lands "
        "inside some test's window and is attributed to it. This fixture cannot "
        "tell the two apart — it sees only that the bytes changed — so the fix "
        "there is to recover your edit from the preserved copy below and re-run, "
        "not to hunt a test. "
        "Restored to its content at the START OF THIS TEST (not of the session, "
        "which would revert every edit made while the suite ran): "
        + (", ".join(restored) if restored else "nothing to restore")
        + ". The overwritten content was preserved first at: "
        + (", ".join(preserved_paths) if preserved_paths else "nothing preserved")
        + "."
    )


@pytest.fixture(autouse=True)
def reset_project_context():
    """Reset ProjectContext singleton after each test.

    ProjectContext is a singleton that can only be initialized once per process.
    This fixture ensures it's reset between tests so each test starts fresh.

    This is an autouse fixture, so it runs automatically for every test.
    """
    yield  # Let the test run
    # After test completes, reset ProjectContext
    ProjectContext.reset()
