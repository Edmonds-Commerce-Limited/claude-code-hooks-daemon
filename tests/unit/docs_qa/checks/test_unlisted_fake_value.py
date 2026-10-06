"""Tests for check ``unlisted-fake-value`` (Plan 00492, Task 2.2)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks import all_checks
from claude_code_hooks_daemon.docs_qa.checks.unlisted_fake_value import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity
from claude_code_hooks_daemon.remote_docs.capture import capture
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH

_LISTED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_UNLISTED = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_REGISTRY = (
    "kinds:\n"
    "  session-uuid:\n"
    "    fake_looking: '\\b([0-9a-f])\\1{7}-\\1{4}-\\1{4}-\\1{4}-\\1{12}\\b'\n"
    f"    values:\n      - '{_LISTED}'\n"
)


def _run(stage: CheckStage, context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is stage:
            return spec.run(context)
    raise AssertionError(f"no {stage} check registered")


def _project(tmp_path: Path, *, registry: str | None = _REGISTRY) -> Path:
    if registry is not None:
        target = tmp_path / REGISTRY_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(registry, encoding="utf-8")
    return tmp_path


def _sweep(root: Path) -> list[Finding]:
    context = sweep_context(root, DocumentationPolicy(), DocCorpus(project_root=root))
    return _run(CheckStage.SWEEP, context)


def _edit(root: Path, relative: str, content: str) -> list[Finding]:
    context = edit_context(
        root, DocumentationPolicy(), root / relative, content, file_exists_before=False
    )
    return _run(CheckStage.EDIT, context)


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        assert {spec.stage for spec in CHECKS} == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)

    def test_is_part_of_the_catalogue(self) -> None:
        assert [spec for spec in all_checks() if spec.check_id == CHECK_ID]


class TestSweep:
    def test_a_listed_fake_is_clean(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        (root / "guide.md").write_text(f"session {_LISTED}\n")
        assert _sweep(root) == []

    def test_an_unlisted_fake_is_a_finding_naming_the_remedy(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        (root / "guide.md").write_text(f"intro\n\nsession {_UNLISTED}\n")
        findings = _sweep(root)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == CHECK_ID
        assert finding.severity is Severity.ADVISE
        assert finding.path == "guide.md"
        assert _UNLISTED in finding.message
        assert "session-uuid" in finding.message
        assert "line 3" in finding.message
        assert REGISTRY_RELATIVE_PATH in finding.remediation
        assert "listed fake" in finding.remediation

    def test_a_vendored_page_is_told_to_recapture_not_edit(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        page = root / "remote-docs" / "example.com" / "page.md"
        page.parent.mkdir(parents=True)
        body = f"upstream {_UNLISTED}\n".encode()
        page.write_text(
            capture("https://example.com/page", fetch_fn=lambda _url: body).content,
            encoding="utf-8",
        )
        findings = [f for f in _sweep(root) if f.path == "remote-docs/example.com/page.md"]
        assert len(findings) == 1
        assert "remote-docs add --force" in findings[0].remediation

    def test_real_looking_values_are_left_to_sensitive_content(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        real_looking = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
        (root / "guide.md").write_text(f"session {real_looking}\n")
        assert _sweep(root) == []

    def test_no_registry_means_no_findings(self, tmp_path: Path) -> None:
        root = _project(tmp_path, registry=None)
        (root / "guide.md").write_text(f"session {_UNLISTED}\n")
        assert _sweep(root) == []

    def test_a_malformed_registry_is_one_finding_about_the_registry(self, tmp_path: Path) -> None:
        root = _project(tmp_path, registry="kinds: [oops")
        (root / "guide.md").write_text(f"session {_UNLISTED}\n")
        findings = _sweep(root)
        assert len(findings) == 1
        assert findings[0].path == REGISTRY_RELATIVE_PATH


class TestEdit:
    def test_an_unlisted_fake_in_the_written_content_is_a_finding(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        findings = _edit(root, "guide.md", f"session {_UNLISTED}\n")
        assert [f.path for f in findings] == ["guide.md"]

    def test_a_listed_fake_is_clean(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        assert _edit(root, "guide.md", f"session {_LISTED}\n") == []

    @pytest.mark.parametrize("relative", ["notes.txt", "pkg/mod.py"])
    def test_non_markdown_is_not_judged(self, tmp_path: Path, relative: str) -> None:
        root = _project(tmp_path)
        assert _edit(root, relative, f"session {_UNLISTED}\n") == []
