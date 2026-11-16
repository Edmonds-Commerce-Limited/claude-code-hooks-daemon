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
