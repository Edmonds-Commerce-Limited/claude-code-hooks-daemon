"""``bin/hooks-daemon repair`` works when there is no venv to run it with (Plan 00456, #53).

The wrapper resolves the venv before it looks at a single argument, so every
verb exits 5 when no venv resolves for this path. That includes ``repair``,
the one verb whose job is to fix exactly that. A new Python subcommand cannot
help, because the gate is in bash, ahead of dispatch (Plan 00431 is the
precedent for moving a check ahead of venv resolution).

``repair`` is therefore intercepted before resolution. With no venv for this
path, the wrapper builds one in the foreground with the clone's
``scripts/venv_bootstrap.sh repair``: the same lock, with no hook timeout to
fit inside. It then continues into the normal Python ``repair``. With a venv
present, nothing about ``repair`` changes. Every other verb still refuses with
exit 5, and now names ``repair`` as the fix.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import (
    Sandbox,
    assert_never_suggests_install_or_force,
    snapshot,
)

#: bin/hooks-daemon's "no venv resolves" exit status.
_NO_VENV_EXIT = 5

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The deployed wrapper and the template it is installed from (byte-identical).
_WRAPPER_COPIES = (
    _REPO_ROOT / "bin" / "hooks-daemon",
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "hooks-daemon",
)

#: The one function that decides which verbs run with no venv.
_DISPATCH_FUNCTION = "_run_venv_free_verb"


def _function_body(script: str, name: str) -> str:
    """Return the text of shell function ``name`` in ``script``, up to its closing brace."""
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}$", script, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"shell function {name}() is not defined")
    return match.group(1)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


class TestRepairWithNoVenv:
    def test_builds_the_venv_and_completes_the_python_repair(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        assert not sandbox.resolves()

        result = sandbox.wrapper("repair")

        output = result.stdout + result.stderr
        assert result.returncode != _NO_VENV_EXIT, output
        assert result.returncode == 0, output
        assert sandbox.resolves()
        assert "Venv repaired successfully" in output, "the Python repair must run afterwards"

    def test_clears_a_failed_build_marker(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(fail=True)
        sandbox.hook()
        sandbox.wait_for_build()
        assert sandbox.failed_markers(), "precondition: the background build failed"

        sandbox.stub_uv()
        result = sandbox.wrapper("repair")

        assert result.returncode == 0, result.stdout + result.stderr
        assert sandbox.failed_markers() == []

    def test_leaves_another_environments_venv_untouched(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        before = snapshot(other)

        assert sandbox.wrapper("repair").returncode == 0

        assert snapshot(other) == before

    def test_uv_missing_names_it_changes_nothing_and_is_not_exit_5(self, sandbox: Sandbox) -> None:
        before = snapshot(sandbox.clone)

        result = sandbox.wrapper("repair")

        output = result.stdout + result.stderr
        assert result.returncode == 1, output
        assert "uv:" in output
        assert_never_suggests_install_or_force(output)
        assert snapshot(sandbox.clone) == before


class TestRepairWithAVenvIsUnchanged:
    def test_goes_straight_to_the_python_repair(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        assert sandbox.wrapper("repair").returncode == 0
        calls = sandbox.root / "driver-calls.log"
        (sandbox.clone / "scripts" / "venv_bootstrap.sh").write_text(
            f'#!/bin/bash\necho "$*" >> "{calls}"\nexit 1\n'
        )

        result = sandbox.wrapper("repair")

        assert result.returncode == 0, result.stdout + result.stderr
        assert not calls.exists(), "with a venv present, the bootstrap driver is not involved"


class TestOtherVerbsStillRefuse:
    def test_status_with_no_venv_exits_5_and_names_repair(self, sandbox: Sandbox) -> None:
        result = sandbox.wrapper("status")

        assert result.returncode == _NO_VENV_EXIT
        assert f"{sandbox.clone}/bin/hooks-daemon repair" in result.stderr
        assert_never_suggests_install_or_force(result.stderr)

    def test_status_with_no_venv_builds_nothing(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        sandbox.wrapper("status")
        assert sandbox.uv_calls() == []


class TestVenvFreeVerbsAreOneDispatch:
    """The pre-resolution intercept is a dispatch table, not a ``repair`` special case.

    ``signal`` (Plan 00457, #55) is the next verb that must run where no venv
    resolves. It should be added as one more arm of the same dispatch, so the
    wrapper must have exactly one place that decides which verbs run without a
    venv, and the exit-5 refusal must be reached only through it.
    """

    @pytest.fixture(params=_WRAPPER_COPIES, ids=lambda path: path.parent.name)
    def wrapper_text(self, request: pytest.FixtureRequest) -> str:
        path: Path = request.param
        return path.read_text()

    def test_the_dispatch_is_one_function_with_a_case_arm_per_verb(self, wrapper_text: str) -> None:
        body = _function_body(wrapper_text, _DISPATCH_FUNCTION)
        assert re.search(r'^\s*case "\$\{1:-\}" in$', body, re.MULTILINE)
        assert re.search(r"^\s*repair\)$", body, re.MULTILINE)
        assert re.search(r"^\s*\*\)$", body, re.MULTILINE)

    def test_the_refusal_is_reached_only_through_the_dispatch(self, wrapper_text: str) -> None:
        assert f'if ! {_DISPATCH_FUNCTION} "$@"; then' in wrapper_text
        assert '"${1:-}" = "repair"' not in wrapper_text
