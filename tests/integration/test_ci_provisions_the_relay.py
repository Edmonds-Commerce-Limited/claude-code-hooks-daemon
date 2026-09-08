"""CI must BUILD the relay, or fourteen transport gates never run there.

Fourteen tests skip on every runner with `relay binary not built` — 11 in
`tests/acceptance/test_transport_toggle_cycle.py` and 3 in
`tests/integration/test_relay_guard_fail_open.py`. The binary is a compiled
artefact under gitignored `untracked/`, so it is absent from every fresh
checkout, and pytest counts a skip as neither a pass nor a failure.

This is Plan 00250's defect one artefact over, and it takes the same shape of
fix: provision the thing the gates need rather than relax the gates. What is
asserted here is only that the workflow still does the provisioning — the
step is one line in a YAML file and nothing else would notice it going away.

**Two paths, not one, and that is the whole trap.** `relay/build.sh` writes
`untracked/relay-build/hooks-relay-<target>`, which is what the three
fail-open tests look for; the eleven toggle-cycle tests look for the DEPLOYED
`untracked/bin/hooks-relay`. Building without deploying fixes 3 of the 14 and
leaves 11 silently skipping, which looks enough like success to stop there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "qa.yml"

#: The step that runs the suite the fourteen gates live in.
_TEST_STEP = "Tests + coverage"

#: What the build script produces, and where the deploy has to put it. Both
#: are asserted because each is read by a different half of the fourteen.
_BUILD_SCRIPT = "relay/build.sh"
_DEPLOYED_PATH = "untracked/bin/hooks-relay"


def _qa_job_steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"]["qa"]["steps"])


def _step_names() -> list[str]:
    return [str(step.get("name", "")) for step in _qa_job_steps()]


def _relay_step() -> dict | None:
    for step in _qa_job_steps():
        if _BUILD_SCRIPT in str(step.get("run", "")):
            return step
    return None


class TestTheWorkflowStillBuildsTheRelay:
    def test_the_qa_job_has_a_step_that_runs_the_build_script(self) -> None:
        assert _relay_step() is not None, (
            f"no step in the qa job runs {_BUILD_SCRIPT}, so the relay binary is "
            "absent on the runner and fourteen transport gates skip — reported as "
            "neither passed nor failed (Plan 00350)"
        )

    def test_the_build_step_also_DEPLOYS_the_binary(self) -> None:
        """Building alone fixes 3 of the 14 and leaves 11 skipping."""
        step = _relay_step()
        assert step is not None
        assert _DEPLOYED_PATH in str(step.get("run", "")), (
            f"the relay step builds but never puts the binary at {_DEPLOYED_PATH}, "
            "which is where the 11 toggle-cycle gates look for it"
        )

    def test_the_musl_target_is_provisioned(self) -> None:
        """A runner's preinstalled rustc has the host target only.

        Measured rather than assumed: with a poisoned `musl-gcc` first on PATH
        the build still succeeds, so rustc's self-contained linking covers it
        and no apt package is needed — but the target's std has to be there.
        """
        step = _relay_step()
        assert step is not None
        assert "x86_64-unknown-linux-musl" in str(step.get("run", ""))

    def test_the_relay_is_built_BEFORE_the_tests_run(self) -> None:
        """Ordering is the point: after the suite, the gates have already skipped."""
        names = _step_names()
        step = _relay_step()
        assert step is not None
        assert _TEST_STEP in names, "the step that runs the suite was renamed"
        assert names.index(str(step.get("name", ""))) < names.index(_TEST_STEP)

    def test_the_step_is_not_allowed_to_fail_quietly(self) -> None:
        """A build that fails open reproduces exactly the skip being removed."""
        step = _relay_step()
        assert step is not None
        run = str(step.get("run", ""))
        assert "|| true" not in run
        assert step.get("continue-on-error") is not True


class TestTheFourteenGatesAreRealAndStillCounted:
    """Vacuity: if the gates moved or vanished, the step above guards nothing."""

    @pytest.mark.parametrize(
        ("relative_path", "expected_marker"),
        [
            ("tests/acceptance/test_transport_toggle_cycle.py", "relay binary not built"),
            ("tests/integration/test_relay_guard_fail_open.py", "no built relay binary"),
        ],
    )
    def test_each_file_still_skips_on_a_missing_binary(
        self, relative_path: str, expected_marker: str
    ) -> None:
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert expected_marker in source, (
            f"{relative_path} no longer skips on a missing relay binary, so the "
            "provisioning step this file guards may no longer be needed — "
            "confirm before deleting either"
        )
