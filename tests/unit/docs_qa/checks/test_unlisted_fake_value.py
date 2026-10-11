"""Tests for check ``unlisted-fake-value`` (Plan 00492, Task 2.2)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks import all_checks
from claude_code_hooks_daemon.docs_qa.checks.unlisted_fake_value import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity
from claude_code_hooks_daemon.remote_docs.capture import capture
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH, parse_fake_values
from tests.support.git_fixtures import git_setup_timeout

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


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=git_setup_timeout(),
    )


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
    def test_registers_edit_staged_and_sweep(self) -> None:
        assert {spec.stage for spec in CHECKS} == {
            CheckStage.EDIT,
            CheckStage.STAGED,
            CheckStage.SWEEP,
        }
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)

    def test_is_part_of_the_catalogue(self) -> None:
        assert [spec for spec in all_checks() if spec.check_id == CHECK_ID]


class TestStagedRegistry:
    """N361 option A: a commit staging a registry entry that is not visibly fake is BLOCKED."""

    _REAL = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))

    @staticmethod
    def _repo(root: Path, registry: str | None) -> None:
        root.mkdir(parents=True, exist_ok=True)
        _git(root, "init")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "T")
        (root / "README.md").write_text("x\n")
        if registry is not None:
            target = root / REGISTRY_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(registry, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")

    @staticmethod
    def _stage_registry(root: Path, registry: str) -> list[Finding]:
        (root / REGISTRY_RELATIVE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / REGISTRY_RELATIVE_PATH).write_text(registry, encoding="utf-8")
        _git(root, "add", "-A")
        context = staged_context(project_root=root, policy=DocumentationPolicy())
        return _run(CheckStage.STAGED, context)

    def test_a_new_real_looking_entry_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, _REGISTRY)
        findings = self._stage_registry(root, _REGISTRY + f"      - '{self._REAL}'\n")
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].check_id == CHECK_ID
        assert findings[0].path == REGISTRY_RELATIVE_PATH
        assert self._REAL in findings[0].message
        assert "session-uuid" in findings[0].message
        assert "obviously fake" in findings[0].remediation

    def test_a_visibly_fake_addition_is_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, _REGISTRY)
        assert self._stage_registry(root, _REGISTRY + "      - 'fakefakefake'\n") == []

    def test_a_whole_new_registry_is_judged(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, None)
        findings = self._stage_registry(root, _REGISTRY + f"      - '{self._REAL}'\n")
        assert [f.severity for f in findings] == [Severity.BLOCK]

    def test_an_entry_already_in_head_is_not_blamed_on_this_commit(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        registry = _REGISTRY + f"      - '{self._REAL}'\n"
        self._repo(root, registry)
        findings = self._stage_registry(root, registry + "      - 'fakefakefake'\n")
        assert findings == []

    def test_a_commit_not_touching_the_registry_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, _REGISTRY + f"      - '{self._REAL}'\n")
        (root / "README.md").write_text("changed\n")
        _git(root, "add", "-A")
        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run(CheckStage.STAGED, context) == []

    def test_a_staged_registry_that_cannot_be_parsed_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, _REGISTRY)
        findings = self._stage_registry(root, "kinds: [not, a, mapping]\n")
        assert [f.severity for f in findings] == [Severity.BLOCK]
        assert findings[0].path == REGISTRY_RELATIVE_PATH

    def test_deleting_the_registry_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        self._repo(root, _REGISTRY)
        (root / REGISTRY_RELATIVE_PATH).unlink()
        _git(root, "add", "-A")
        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run(CheckStage.STAGED, context) == []

    def test_the_shipped_registry_would_not_be_denied(self) -> None:
        """Every current entry passes, so staging the file as it stands blocks nothing."""
        root = Path(__file__).resolve().parents[4]
        text = (root / REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")
        registry = parse_fake_values(text, root / REGISTRY_RELATIVE_PATH)
        assert registry.not_visibly_fake() == []


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

    def test_an_unreadable_document_is_a_finding_and_the_sweep_goes_on(
        self, tmp_path: Path
    ) -> None:
        """N374: a document the sweep could not read must not look like a clean one."""
        root = _project(tmp_path)
        (root / "binary.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")
        (root / "guide.md").write_text(f"session {_UNLISTED}\n")

        findings = _sweep(root)

        unreadable = [f for f in findings if f.path == "binary.md"]
        assert len(unreadable) == 1
        assert unreadable[0].check_id == CHECK_ID
        assert unreadable[0].severity is Severity.ADVISE
        assert "could not be read" in unreadable[0].message
        assert "binary.md" in unreadable[0].message
        assert [f.path for f in findings if f.path != "binary.md"] == ["guide.md"]

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


class TestRegistryEntriesMustLookFake:
    """N361 (owner ruling C7): a registry entry that does not look fake is a finding."""

    def test_a_real_looking_entry_is_a_finding_on_the_registry(self, tmp_path: Path) -> None:
        real_looking = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
        root = _project(tmp_path, registry=_REGISTRY + f"      - '{real_looking}'\n")
        findings = _sweep(root)
        assert len(findings) == 1
        assert findings[0].path == REGISTRY_RELATIVE_PATH
        assert findings[0].severity is Severity.ADVISE
        assert real_looking in findings[0].message
        assert "session-uuid" in findings[0].message
        assert "obviously fake" in findings[0].remediation

    def test_an_all_fake_registry_is_clean(self, tmp_path: Path) -> None:
        assert _sweep(_project(tmp_path)) == []
