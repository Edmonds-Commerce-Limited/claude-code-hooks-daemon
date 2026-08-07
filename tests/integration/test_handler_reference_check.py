"""``docs/guides/HANDLER_REFERENCE.md`` must agree with the handler code.

DBF (``CLAUDE.md`` Core Standard 15). ``docs/CLAUDE.md`` names
``docs/guides/HANDLER_REFERENCE.md`` the canonical source for per-handler
options, values and defaults — and it had drifted badly:

- FIVE ``#### <name>`` sections documented handlers that do not exist
  (``python_qa_suppression_blocker``, ``php_qa_suppression_blocker``,
  ``go_qa_suppression_blocker``, ``eslint_disable`` — all long since collapsed
  into the single ``qa_suppression`` handler — plus ``stats_cache_reader``,
  which is a helper MODULE, not a handler). Each carried a copy-pasteable YAML
  block that hard-fails config validation with ``Unknown handler '...'``.
- ~30 documented priorities contradicted ``constants/priority.py``.
  ``sed_blocker`` even contradicted itself: heading 10, own snippet 11.

None of that was caught because **no guard could see it**. The ground truth
existed the whole time (``constants/handlers.py``, ``constants/priority.py``,
the handler registry); the doc simply had no consumer. This is that consumer.

Every positive case below is paired with the negative control
``test_accurate_reference_passes`` — a checker that flagged everything would
satisfy the positive cases while being worthless.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "qa" / "check_handler_reference.py"
_TIMEOUT_SECONDS = 120

_DOC_RELATIVE_PARTS = ("docs", "guides", "HANDLER_REFERENCE.md")
_GENERATED_RELATIVE_PARTS = (".claude", "HOOKS-DAEMON.md")
_TOOL_KEY = "handler_reference"

# A minimal stand-in for the generated `.claude/HOOKS-DAEMON.md`. Only the
# PreToolUse blocking rows matter to the coverage rule; `british_english` is
# present so the fixture proves ADVISORY rows are NOT required to be documented.
_GENERATED_DOC = """# Hooks Daemon - Active Configuration

## Active Handlers

### PreToolUse (2 handlers)

| Priority | Handler | Behavior | Description |
|----------|---------|----------|-------------|
| 10 | destructive_git | BLOCKING | Block destructive git commands |
| 60 | british_english | ADVISORY | Warn about American spellings |
"""

# An accurate section for `destructive_git`. Priority 10 is
# `Priority.DESTRUCTIVE_GIT`; documenting it satisfies the coverage rule too.
_ACCURATE_SECTION = """# Handler Reference

#### destructive_git

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `destructive_git` |
| **Priority**   | 10                |
| **Type**       | Blocking          |
| **Event**      | PreToolUse        |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
```
"""


def _run_checker(root: Path) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), "--report-stdout"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode == 2:
        return result.returncode, {"violations": [], "stderr": result.stderr}
    assert result.stdout, f"checker produced no report. stderr: {result.stderr[:500]}"
    return result.returncode, json.loads(result.stdout)


def _make_root(tmp_path: Path, reference_doc: str) -> Path:
    """Build a fixture tree carrying a reference doc plus the generated truth."""
    root = tmp_path / "fixture"
    doc_path = root.joinpath(*_DOC_RELATIVE_PARTS)
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text(reference_doc, encoding="utf-8")
    generated = root.joinpath(*_GENERATED_RELATIVE_PARTS)
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(_GENERATED_DOC, encoding="utf-8")
    return root


def _rules(report: dict) -> set[str]:
    return {v["rule"] for v in report["violations"]}


def test_flags_a_section_heading_naming_a_handler_that_does_not_exist(tmp_path: Path) -> None:
    """The shipped bug: four collapsed handlers still had their own sections.

    Copying such a section's YAML hard-fails config validation with
    ``Unknown handler 'python_qa_suppression_blocker'``.
    """
    root = _make_root(
        tmp_path,
        _ACCURATE_SECTION + """
#### python_qa_suppression_blocker

| Property       | Value                           |
| -------------- | ------------------------------- |
| **Config key** | `python_qa_suppression_blocker` |
| **Priority**   | 26                              |
| **Type**       | Blocking                        |
| **Event**      | PreToolUse                      |
""",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "a section for a non-existent handler must fail the check"
    assert "handler-ref-unknown" in _rules(report)
    assert any("python_qa_suppression_blocker" in v["message"] for v in report["violations"])


def test_flags_a_documented_priority_that_contradicts_the_code(tmp_path: Path) -> None:
    """``constants/priority.py`` is the single source of truth for priorities."""
    doc = _ACCURATE_SECTION.replace(
        "| **Priority**   | 10                |", "| **Priority**   | 99                |"
    )
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "a priority contradicting priority.py must fail the check"
    assert "priority-mismatch" in _rules(report)


def test_flags_a_config_example_priority_that_contradicts_its_own_heading(
    tmp_path: Path,
) -> None:
    """The ``sed_blocker`` self-contradiction: heading said 10, its snippet said 11."""
    doc = _ACCURATE_SECTION.replace("      priority: 10", "      priority: 11")
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "a config example contradicting priority.py must fail"
    assert "priority-mismatch" in _rules(report)


def test_flags_a_section_whose_config_key_contradicts_its_heading(tmp_path: Path) -> None:
    """A renamed heading with a stale ``Config key`` row sends users to a dead key."""
    doc = _ACCURATE_SECTION.replace(
        "| **Config key** | `destructive_git` |", "| **Config key** | `git_destructive` |"
    )
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "config-key-mismatch" in _rules(report)


def test_flags_a_quick_reference_row_naming_an_unknown_handler(tmp_path: Path) -> None:
    """The phantom keys also lived in the summary tables, not just the sections."""
    doc = _ACCURATE_SECTION + (
        "\n## Quick Reference Table\n\n"
        "| Config Key       | Event      | Priority | What It Blocks |\n"
        "| ---------------- | ---------- | -------- | -------------- |\n"
        "| `eslint_disable` | PreToolUse | 30       | eslint-disable |\n"
    )
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "handler-ref-unknown" in _rules(report)


def test_flags_a_quick_reference_row_with_the_wrong_priority(tmp_path: Path) -> None:
    """Summary-table priorities drift exactly like the per-section ones."""
    doc = _ACCURATE_SECTION + (
        "\n## Quick Reference Table\n\n"
        "| Config Key        | Event      | Priority | What It Blocks |\n"
        "| ----------------- | ---------- | -------- | -------------- |\n"
        "| `destructive_git` | PreToolUse | 42       | git reset      |\n"
    )
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "priority-mismatch" in _rules(report)


def test_flags_an_undocumented_pretooluse_blocking_handler(tmp_path: Path) -> None:
    """A blocking handler nobody documented cannot be diagnosed when it fires.

    ``qa_suppression``, ``security_antipattern``, ``error_hiding_blocker``,
    ``root_recursion_guard``, ``lsp_enforcement``, ``ask_user_question_blocker``,
    ``gh_pr_comments`` and ``daemon_location_guard`` were all in this state.
    """
    generated = _GENERATED_DOC + "| 30 | qa_suppression | BLOCKING | Block QA suppression |\n"
    root = _make_root(tmp_path, _ACCURATE_SECTION)
    root.joinpath(*_GENERATED_RELATIVE_PARTS).write_text(generated, encoding="utf-8")

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "an undocumented PreToolUse blocking handler must fail"
    assert "undocumented-blocking-handler" in _rules(report)
    assert any("qa_suppression" in v["message"] for v in report["violations"])


def test_flags_a_documented_priority_with_no_priority_constant(tmp_path: Path) -> None:
    """``priority.py`` claims to be the SSoT; a handler bypassing it is a finding.

    ``worktree_create`` sets its priority from a module-local constant, so the
    documented number cannot be verified against the declared single source of
    truth. Say so rather than silently skipping — a guard that quietly checks
    nothing is the failure this whole check exists to prevent.
    """
    doc = _ACCURATE_SECTION + """
#### worktree_create

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `worktree_create` |
| **Priority**   | 50                |
| **Type**       | Terminal          |
| **Event**      | WorktreeCreate    |
"""
    root = _make_root(tmp_path, doc)

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "priority-unresolvable" in _rules(report)


def test_accurate_reference_passes(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — the check must discriminate, not merely fire.

    A real handler, its real priority, a self-consistent config key and a
    matching config example must produce ZERO findings. Without this, a
    checker that flagged every heading would satisfy every positive case
    above while being useless.
    """
    root = _make_root(tmp_path, _ACCURATE_SECTION)

    exit_code, report = _run_checker(root)

    assert exit_code == 0, f"an accurate reference was flagged: {report['violations']}"
    assert report["violations"] == []


def test_missing_reference_doc_is_an_operational_failure(tmp_path: Path) -> None:
    """FAIL FAST — a check with nothing to read must not report 'clean'."""
    root = tmp_path / "empty"
    root.mkdir()

    exit_code, _report = _run_checker(root)

    assert exit_code == 2


def test_check_is_wired_into_the_llm_qa_runner() -> None:
    """An unwired check is a check nobody runs — the blind-guard failure again."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "qa"))
    import llm_qa

    assert (
        _TOOL_KEY in llm_qa.TOOL_REGISTRY
    ), f"missing from TOOL_REGISTRY: {list(llm_qa.TOOL_REGISTRY)}"
    assert _TOOL_KEY in llm_qa.SUMMARIZERS, "TOOL_REGISTRY entry has no summarizer"
    assert llm_qa.TOOL_REGISTRY[_TOOL_KEY].json_file == "handler_reference.json"
    assert list(llm_qa.TOOL_REGISTRY)[-1] == "smoke_test", (
        "smoke_test must remain the LAST registry entry — it probes the live "
        "daemon, so it belongs after every static check."
    )


def test_check_is_wired_into_run_all() -> None:
    """``run_all.sh`` is the release gate; a check absent from it does not gate."""
    run_all = (REPO_ROOT / "scripts" / "qa" / "run_all.sh").read_text(encoding="utf-8")

    assert "check_handler_reference.py" in run_all, "run_all.sh never invokes the check"
    assert "handler_reference.json" in run_all, "run_all.sh omits the check from its summary"


def test_real_repository_handler_reference_is_accurate() -> None:
    """The gate itself: this repository's handler reference must match the code."""
    exit_code, report = _run_checker(REPO_ROOT)

    assert exit_code == 0, "HANDLER_REFERENCE.md contradicts the handler code:\n" + "\n".join(
        f"  [{v['rule']}] {v['file']}:{v['line']}: {v['message']}" for v in report["violations"]
    )
