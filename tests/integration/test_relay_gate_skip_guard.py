"""A relay gate that skips WHERE THE RELAY IS PROVISIONED is a failure.

Fourteen transport gates skipped on every CI runner because the relay binary
is a compiled artefact under gitignored `untracked/`. The workflow now builds
and deploys it, so on a runner their skip condition is unreachable — and a skip
that reappears there means the provisioning silently stopped working, which is
precisely the state this plan removes (Plan 00350).

**Scoped to CI on purpose.** A developer without a Rust toolchain genuinely
cannot run these, and turning their skip into a failure would punish them for
an honest limitation. CI has no such excuse: the build step is three lines and
costs about a second. So the guard keys on `CI`, which GitHub Actions sets, and
changes nothing locally.

**It also does not touch `RELEASING.md`.** Adding these files to Step 12.0's
declaration would make them release-blocking gates, which is a decision about
release scope rather than about CI visibility — the same distinction Plan 00250
Task 1.2 left to the owner rather than making on its own.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted interpreter, list form, for a nested pytest run
import sys
import textwrap
from pathlib import Path

import pytest

from tests.relay_gate_guard import (
    RELAY_SKIP_MARKERS,
    relay_skip_failure_message,
    skip_is_a_provisioning_failure,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestTheMarkersMatchWhatTheGatesActuallySay:
    """Vacuity: a marker that no test emits guards nothing."""

    @pytest.mark.parametrize(
        ("relative_path", "marker"),
        [
            ("tests/acceptance/test_transport_toggle_cycle.py", "relay binary not built"),
            ("tests/integration/test_relay_guard_fail_open.py", "no built relay binary"),
        ],
    )
    def test_each_marker_appears_in_the_file_it_is_for(
        self, relative_path: str, marker: str
    ) -> None:
        assert marker in RELAY_SKIP_MARKERS
        assert marker in (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class TestThePredicate:
    def test_a_relay_skip_in_ci_is_a_failure(self) -> None:
        assert skip_is_a_provisioning_failure(
            "relay binary not built: /x/untracked/bin/hooks-relay", in_ci=True
        )

    def test_the_same_skip_outside_ci_is_left_alone(self) -> None:
        """A developer with no Rust toolchain is not the defect."""
        assert not skip_is_a_provisioning_failure(
            "relay binary not built: /x/untracked/bin/hooks-relay", in_ci=False
        )

    def test_the_other_files_marker_is_recognised_too(self) -> None:
        assert skip_is_a_provisioning_failure("no built relay binary on this machine", in_ci=True)

    def test_an_unrelated_skip_is_not_claimed(self) -> None:
        """The guard must not turn every environment skip into a failure."""
        assert not skip_is_a_provisioning_failure("Running as root", in_ci=True)

    def test_an_empty_reason_is_not_claimed(self) -> None:
        assert not skip_is_a_provisioning_failure("", in_ci=True)


class TestTheMessageTellsYouWhatBroke:
    def test_it_names_the_provisioning_step_and_the_original_reason(self) -> None:
        message = relay_skip_failure_message("relay binary not built: /x/bin/hooks-relay")
        assert "relay binary not built: /x/bin/hooks-relay" in message
        assert "relay/build.sh" in message
        assert "untracked/bin/hooks-relay" in message


class TestEndToEndInANestedPytestRun:
    """The predicate can be right while the hook is wired wrong."""

    @staticmethod
    def _run_nested_pytest(tmp_path: Path, *, ci: str | None) -> subprocess.CompletedProcess[str]:
        (tmp_path / "conftest.py").write_text(
            textwrap.dedent(f"""
                import sys

                sys.path.insert(0, {str(REPO_ROOT)!r})

                from tests.relay_gate_guard import pytest_runtest_makereport

                __all__ = ["pytest_runtest_makereport"]
                """).lstrip(),
            encoding="utf-8",
        )
        (tmp_path / "test_relay_gate.py").write_text(
            textwrap.dedent("""
                import pytest


                def test_needs_the_relay():
                    pytest.skip("relay binary not built: /x/untracked/bin/hooks-relay")


                def test_unrelated_skip():
                    pytest.skip("Running as root")
                """).lstrip(),
            encoding="utf-8",
        )

        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        if ci is not None:
            env["CI"] = ci

        return subprocess.run(  # nosec B603 - trusted interpreter, list form
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"--rootdir={tmp_path}",
                "-rs",
                str(tmp_path),
            ],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_in_ci_the_relay_skip_fails_and_the_unrelated_one_does_not(
        self, tmp_path: Path
    ) -> None:
        result = self._run_nested_pytest(tmp_path, ci="true")
        assert result.returncode != 0, f"{result.stdout}\n{result.stderr}"
        assert "1 failed" in result.stdout
        assert "1 skipped" in result.stdout
        assert "relay/build.sh" in result.stdout

    def test_outside_ci_both_still_skip(self, tmp_path: Path) -> None:
        result = self._run_nested_pytest(tmp_path, ci=None)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "2 skipped" in result.stdout
