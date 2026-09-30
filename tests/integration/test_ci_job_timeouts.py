"""Every CI job declares a timeout (ledger 00474 N273).

A job with no ``timeout-minutes`` inherits GitHub's six-hour default. The
workflow's concurrency group keeps one queued run, so a single stalled job
held main's next run for hours: the run carrying a red-main fix waited behind
a Shell job that had stopped producing output.
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "qa.yml"

#: Above every measured job duration, below GitHub's 360-minute default.
MAX_TIMEOUT_MINUTES = 180


def _jobs() -> dict[str, dict[str, object]]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs: dict[str, dict[str, object]] = document["jobs"]
    return jobs


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

    assert too_long == {}, f"timeouts missing, non-integer or over {MAX_TIMEOUT_MINUTES}: {too_long}"
