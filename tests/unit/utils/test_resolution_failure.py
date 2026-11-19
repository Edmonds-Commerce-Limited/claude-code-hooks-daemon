"""A failure while placing a command's words is reported as one, never as an answer."""

from collections.abc import Callable

import pytest

from claude_code_hooks_daemon.utils import shell_expansion
from claude_code_hooks_daemon.utils.resolution_failure import (
    ResolutionFailedError,
    fails_closed,
)


def _raising(error: BaseException) -> Callable[[], None]:
    @fails_closed
    def resolve() -> None:
        raise error

    return resolve


@pytest.mark.parametrize("error", [RuntimeError("x"), OSError(36, "long"), ValueError("nul")])
def test_an_unexpected_raise_becomes_a_resolution_failure(error: BaseException) -> None:
    with pytest.raises(ResolutionFailedError) as caught:
        _raising(error)()
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        shell_expansion.TooManyToEnumerateError("cap"),
        ResolutionFailedError("already"),
    ],
)
def test_scan_limits_pass_through_unchanged(error: BaseException) -> None:
    with pytest.raises(type(error)) as caught:
        _raising(error)()
    assert caught.value is error


def test_a_result_is_returned_unchanged() -> None:
    @fails_closed
    def resolve(value: int) -> int:
        return value * 2

    assert resolve(21) == 42


def test_a_failed_placement_is_a_finding_on_the_first_pattern() -> None:
    from claude_code_hooks_daemon.utils.resolution_failure import fail_closed_finding

    assert fail_closed_finding(("a/**", "b/**"), "unplaced") == ("a/**", "unplaced")


def test_with_nothing_protected_a_failed_placement_finds_nothing() -> None:
    from claude_code_hooks_daemon.utils.resolution_failure import fail_closed_finding

    assert fail_closed_finding((), "unplaced") is None


@pytest.mark.parametrize(
    "path",
    [
        "/proc/self/cwd/x",
        "/proc/thread-self/cwd/x",
        "/dev/fd/../cwd/x",
        "//proc//self/./cwd/x",
        "/tmp/../proc/self/cwd",
        "/proc/self",
        "/proc/self/root/etc/passwd",
        "/proc/self/fd/3",
        "/proc/self/exe",
        "/proc/self/task/1/cwd/x",
        "/proc/self/map_files/x",
        "/proc/self/*",
        "/proc/self/c?d",
        "/proc/self/status/../cwd/x",
        "/proc/self/status/x",
        "/proc/thread-self/root",
        "/dev/fd/3",
        "/dev/fd",
    ],
)
def test_a_path_through_the_daemons_own_process_view_cannot_be_placed(path: str) -> None:
    from claude_code_hooks_daemon.utils.resolution_failure import refuse_process_view

    with pytest.raises(ResolutionFailedError):
        refuse_process_view(path)


@pytest.mark.parametrize(
    "path",
    [
        "/proc/version",
        "/proc/1/status",
        "/dev/null",
        "src/selfish/proc",
        "/proc/self/status",
        "//proc//self/./cgroup",
        "/proc/thread-self/status",
        "/proc/self/mountinfo",
    ],
)
def test_other_paths_are_placed(path: str) -> None:
    from claude_code_hooks_daemon.utils.resolution_failure import refuse_process_view

    refuse_process_view(path)
