"""Pytest configuration and shared fixtures for hooks daemon tests.

This module provides test fixtures and utilities used across all test files.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
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


@pytest.fixture(scope="session")
def _tracked_doc_snapshot() -> dict[str, bytes]:
    """Byte snapshot of the protected files, taken ONCE for the session.

    Restoring from this rather than from ``git checkout --`` matters: the
    developer may have legitimate uncommitted edits in these files when the
    suite runs, and a diagnostic fixture must not be the thing that throws
    them away. It also keeps the suite from running a destructive git command
    that this project blocks agents from using at all.
    """
    snapshot: dict[str, bytes] = {}
    for relative in _TRACKED_FILES_NO_TEST_MAY_WRITE:
        path = _REPO_ROOT / relative
        try:
            snapshot[relative] = path.read_bytes()
        except OSError:
            continue
    return snapshot


@pytest.fixture(autouse=True)
def no_test_writes_tracked_generated_docs(_tracked_doc_snapshot: dict[str, bytes]):
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
    """
    before = _tracked_file_fingerprints()
    yield
    after = _tracked_file_fingerprints()

    mutated = [name for name, fingerprint in after.items() if before.get(name) != fingerprint]
    if not mutated:
        return

    # Put the file back exactly as the session found it, so a diagnostic never
    # leaves the developer's tree damaged.
    restored = []
    for name in mutated:
        original = _tracked_doc_snapshot.get(name)
        if original is None:
            continue
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
        "there is to re-apply your edit and re-run, not to hunt a test. "
        "Restored to its "
        "pre-suite content: " + (", ".join(restored) if restored else "nothing to restore") + "."
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
