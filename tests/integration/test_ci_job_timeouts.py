"""Every CI job declares a timeout (ledger 00474 N273).

A job with no ``timeout-minutes`` inherits GitHub's six-hour default. The
workflow's concurrency group keeps one queued run, so a single stalled job
held main's next run for hours: the run carrying a red-main fix waited behind
a Shell job that had stopped producing output.
"""

from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
#: qa.yml and the reusable workflow it calls for the suite (Plan 00572).
WORKFLOWS = (WORKFLOWS_DIR / "qa.yml", WORKFLOWS_DIR / "test-shards.yml")

#: Above every measured job duration, below GitHub's 360-minute default.
MAX_TIMEOUT_MINUTES = 180


def _jobs() -> dict[str, dict[str, object]]:
    """Every job that runs on a runner. A job that CALLS a reusable workflow
    (``uses:``) cannot carry a timeout; the called workflow's jobs do, and are
    included here."""
    jobs: dict[str, dict[str, object]] = {}
    for workflow in WORKFLOWS:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for name, job in document["jobs"].items():
            if "uses" not in job:
                jobs[f"{workflow.name}:{name}"] = job
    return jobs


def test_the_called_workflow_is_one_this_file_reads() -> None:
    """A new reusable workflow must join WORKFLOWS, or its jobs go unchecked."""
    called = set()
    for workflow in WORKFLOWS:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        called |= {str(job["uses"]) for job in document["jobs"].values() if "uses" in job}
    assert called <= {f"./.github/workflows/{w.name}" for w in WORKFLOWS}


def test_release_slate_job_prefixes_name_full_tier_jobs_declared_in_qa_yml() -> None:
    """release_slate keys on CI job names; each prefix must match a job qa.yml
    declares and that job must run on the full tier (Defence Before Fix)."""
    from claude_code_hooks_daemon.core.release_slate import (
        STATIC_JOB_PREFIX,
        SUITE_JOB_PREFIX,
    )

    declared = yaml.safe_load(WORKFLOWS[0].read_text(encoding="utf-8"))["jobs"].values()
    full_tier = "needs.classify.outputs.tier == 'full'"

    def full_tier_names(*, reusable: bool) -> list[str]:
        return [
            f"{job['name']} / " if reusable else str(job["name"])
            for job in declared
            if ("uses" in job) is reusable and full_tier in str(job.get("if", ""))
        ]

    assert any(n.startswith(STATIC_JOB_PREFIX) for n in full_tier_names(reusable=False))
    assert SUITE_JOB_PREFIX in full_tier_names(reusable=True)


def test_every_job_declares_a_timeout() -> None:
    missing = [name for name, job in _jobs().items() if "timeout-minutes" not in job]

    assert missing == [], f"jobs with no timeout-minutes: {missing}"


def test_every_timeout_is_below_the_github_default() -> None:
    too_long = {
        name: job["timeout-minutes"]
        for name, job in _jobs().items()
        if not isinstance(job.get("timeout-minutes"), int)
        or not 0 < int(str(job["timeout-minutes"])) <= MAX_TIMEOUT_MINUTES
    }

    assert (
        too_long == {}
    ), f"timeouts missing, non-integer or over {MAX_TIMEOUT_MINUTES}: {too_long}"
