"""Both QA verbs' ``--json`` findings name severity the same way (Plan 00375).

``plan-qa --json`` named the field ``level`` while ``docs-qa --json`` named the
same concept ``severity`` — same shape, same two values. A reader that knew
only one name silently dropped every finding from the other verb, and one did:
the corpus wrapper counted ``severity``, so plan findings fell out of the split
while still counting toward the total, and it printed a summary contradicting
itself (``3 findings (0 block, 0 advise)``).

``severity`` is the surviving name. ``plan-qa`` emits ``level`` alongside it for
a deprecation window because ``--json`` is documented public API, so a consumer
parsing the old key keeps working.
"""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.cli import cmd_docs_qa, cmd_plan_qa
from claude_code_hooks_daemon.docs_qa.types import Severity
from claude_code_hooks_daemon.plan_qa.types import Level

CANONICAL_SEVERITY_KEY = "severity"
DEPRECATED_SEVERITY_KEYS = frozenset({"level"})
SEVERITY_VALUES = frozenset(
    {member.value for member in Level} | {member.value for member in Severity}
)


def _args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        sweep=True,
        check_staged=False,
        lint=None,
        json_output=True,
    )


def _drifted_plan_tree(tmp_path: Path) -> Path:
    """Git repo whose plan tree has one terminal plan loitering, unindexed."""
    root = tmp_path / "plan-repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("plan_workflow:\n  enabled: true\n")
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    (folder / "JOURNAL").mkdir()
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    rogue = plan_dir / "00002-rogue"
    rogue.mkdir()
    (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return root


def _drifted_docs_corpus(tmp_path: Path) -> Path:
    """Project whose doc corpus has one pointer that resolves to nothing."""
    root = tmp_path / "docs-repo"
    (root / "CLAUDE").mkdir(parents=True)
    (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[missing](Nope.md)\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("version: '2.0'\n")
    # Self-install marker so _daemon_untracked_dir resolves to root/untracked.
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return root


def _plan_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    assert cmd_plan_qa(_args(_drifted_plan_tree(tmp_path))) == 1
    findings = json.loads(capsys.readouterr().out)
    assert findings, "the drifted plan tree must produce at least one finding"
    return findings


def _docs_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    assert cmd_docs_qa(_args(_drifted_docs_corpus(tmp_path))) == 1
    findings = json.loads(capsys.readouterr().out)
    assert findings, "the drifted doc corpus must produce at least one finding"
    return findings


def _severity_bearing_keys(finding: dict[str, object]) -> set[str]:
    return {key for key, value in finding.items() if value in SEVERITY_VALUES}


class TestTheCanonicalKey:
    def test_the_plan_verb_names_severity_canonically(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _plan_findings(tmp_path, capsys):
            assert CANONICAL_SEVERITY_KEY in finding

    def test_the_docs_verb_names_severity_canonically(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _docs_findings(tmp_path, capsys):
            assert CANONICAL_SEVERITY_KEY in finding

    def test_the_canonical_value_is_a_real_severity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _plan_findings(tmp_path, capsys):
            assert finding[CANONICAL_SEVERITY_KEY] in SEVERITY_VALUES


class TestTheDeprecationWindow:
    def test_the_plan_verb_still_carries_the_old_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A consumer parsing ``level`` keeps working until Phase 2 drops it."""
        for finding in _plan_findings(tmp_path, capsys):
            assert "level" in finding

    def test_the_old_key_never_disagrees_with_the_new_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _plan_findings(tmp_path, capsys):
            assert finding["level"] == finding[CANONICAL_SEVERITY_KEY]


class TestNeitherVerbCanInventAThirdName:
    """The class guard: a future third spelling fails here rather than silently.

    Both readers of this output key on a name. Asserting the presence of
    ``severity`` alone would still pass if a verb grew a third severity-valued
    field, which is precisely the failure this plan exists to close — so every
    severity-valued key is enumerated, and anything beyond the canonical name
    must be a declared deprecation.
    """

    def test_the_plan_verb_names_no_undeclared_severity_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _plan_findings(tmp_path, capsys):
            extra = _severity_bearing_keys(finding) - {CANONICAL_SEVERITY_KEY}
            assert extra <= DEPRECATED_SEVERITY_KEYS

    def test_the_docs_verb_names_no_undeclared_severity_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for finding in _docs_findings(tmp_path, capsys):
            extra = _severity_bearing_keys(finding) - {CANONICAL_SEVERITY_KEY}
            assert extra <= DEPRECATED_SEVERITY_KEYS

    def test_both_verbs_agree_on_the_canonical_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = _plan_findings(tmp_path, capsys)
        docs = _docs_findings(tmp_path, capsys)
        shared = set.intersection(*(_severity_bearing_keys(finding) for finding in plan + docs))
        assert shared == {CANONICAL_SEVERITY_KEY}
