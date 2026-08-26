"""Tests for scripts/qa/check_input_contract.py (Plan 00273).

The checker derives the daemon's top-level hook_input READ surface via AST
scan (handlers per event package + shared utils helpers) and applies the
Technical Decision 1 SUPERSET rule against the vendored ``input_example``s:
flag only a field the daemon reads that appears in NO vendored example for
that event; never flag absence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPTS_QA_DIR = Path(__file__).resolve().parents[3] / "scripts" / "qa"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_input_contract", _SCRIPTS_QA_DIR / "check_input_contract.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_input_contract", module)
    spec.loader.exec_module(module)
    return module


cic = _load_module()


# ── collect_reads_from_source ─────────────────────────────────────


class TestCollectReads:
    def test_string_literal_get_and_subscript(self) -> None:
        source = textwrap.dedent("""
            def matches(self, hook_input: dict) -> bool:
                a = hook_input.get("tool_name")
                b = hook_input["prompt"]
                return bool(a or b)
            """)
        assert cic.collect_reads_from_source(source, {}) == {"tool_name", "prompt"}

    def test_hook_input_field_attribute_resolved_via_constants(self) -> None:
        source = textwrap.dedent("""
            def handle(self, hook_input: dict):
                return hook_input.get(HookInputField.TRANSCRIPT_PATH)
            """)
        constants = {"TRANSCRIPT_PATH": "transcript_path"}
        assert cic.collect_reads_from_source(source, constants) == {"transcript_path"}

    def test_nested_tool_input_reads_record_only_top_level_key(self) -> None:
        source = textwrap.dedent("""
            def matches(self, hook_input: dict) -> bool:
                return "x" in hook_input.get("tool_input", {}).get("command", "")
            """)
        assert cic.collect_reads_from_source(source, {}) == {"tool_input"}

    def test_other_dict_reads_are_ignored(self) -> None:
        source = 'def f(options: dict):\n    return options.get("mode")\n'
        assert cic.collect_reads_from_source(source, {}) == set()

    def test_get_with_default_argument(self) -> None:
        source = (
            "def f(hook_input: dict):\n" '    return hook_input.get("stop_hook_active", False)\n'
        )
        assert cic.collect_reads_from_source(source, {}) == {"stop_hook_active"}


# ── event package name mapping ────────────────────────────────────


class TestEventNameMapping:
    def test_snake_package_to_pascal_event(self) -> None:
        assert cic.package_to_event("pre_tool_use") == "PreToolUse"
        assert cic.package_to_event("user_prompt_submit") == "UserPromptSubmit"
        assert cic.package_to_event("stop") == "Stop"


# ── superset rule ─────────────────────────────────────────────────


class TestSupersetRule:
    def _examples(self) -> dict[str, set[str]]:
        return {
            "Stop": {"session_id", "stop_hook_active", "transcript_path"},
            "PreToolUse": {"session_id", "tool_name", "tool_input"},
        }

    def test_field_in_example_is_not_flagged(self) -> None:
        reads = {"Stop": {"stop_hook_active"}}
        assert cic.check_read_surface(reads, self._examples()) == []

    def test_absence_is_never_flagged(self) -> None:
        # The daemon reading FEWER fields than the example shows is fine.
        reads = {"Stop": set()}
        assert cic.check_read_surface(reads, self._examples()) == []

    def test_field_in_no_example_for_event_is_flagged(self) -> None:
        reads = {"Stop": {"stopHookActive"}}
        findings = cic.check_read_surface(reads, self._examples())
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule == cic.RULE_UNKNOWN_INPUT_FIELD
        assert finding.event == "Stop"
        assert finding.subject == "stopHookActive"

    def test_shared_reads_checked_against_union(self) -> None:
        reads = {cic.SHARED_SURFACE: {"transcript_path", "nonsense_field"}}
        findings = cic.check_read_surface(reads, self._examples())
        assert [f.subject for f in findings] == ["nonsense_field"]
        assert findings[0].event == cic.SHARED_SURFACE

    def test_event_without_example_is_skipped(self) -> None:
        examples = {"Stop": set()}
        reads = {"Stop": {"anything"}}
        assert cic.check_read_surface(reads, examples) == []


# ── scan against a synthetic tree ─────────────────────────────────


def _write_tree(
    root: Path,
    *,
    handler_source: str,
    stop_example: dict[str, object],
    allowlist: str | None = None,
    core_source: str | None = None,
) -> None:
    src = root / "src" / "claude_code_hooks_daemon"
    (src / "handlers" / "stop").mkdir(parents=True)
    (src / "handlers" / "stop" / "__init__.py").write_text("")
    (src / "handlers" / "stop" / "my_handler.py").write_text(handler_source)
    (src / "utils").mkdir(parents=True)
    if core_source is not None:
        (src / "core").mkdir(parents=True)
        (src / "core" / "helper.py").write_text(core_source)
    (src / "constants").mkdir(parents=True)
    (src / "constants" / "protocol.py").write_text(
        'class HookInputField:\n    TRANSCRIPT_PATH = "transcript_path"\n'
    )
    contracts = root / "contracts" / "claude-code-hooks"
    contracts.mkdir(parents=True)
    (contracts / "Stop.json").write_text(
        json.dumps({"event": "Stop", "input_example": stop_example})
    )
    if allowlist is not None:
        (contracts / cic.INPUT_ALLOWLIST_FILENAME).write_text(allowlist)


_CLEAN_HANDLER = (
    "def matches(hook_input: dict) -> bool:\n"
    '    return bool(hook_input.get("stop_hook_active"))\n'
)


class TestScan:
    def test_green_when_reads_covered_by_example(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        report = cic.scan(tmp_path)
        assert report.passed

    def test_renamed_example_field_is_reported(self, tmp_path: Path) -> None:
        # Success criterion: mutate the vendored example (rename a field the
        # daemon reads) and the checker reports it.
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_active": True},
        )
        report = cic.scan(tmp_path)
        assert not report.passed
        ids = [f.finding_id for f in report.violations]
        assert f"{cic.RULE_UNKNOWN_INPUT_FIELD}:Stop:stop_hook_active" in ids

    def test_allowlisted_finding_is_recorded_not_violated(self, tmp_path: Path) -> None:
        allowlist = textwrap.dedent("""
            entries:
              - id: "unknown-input-field:Stop:stop_hook_active"
                reason: "deliberate legacy fallback"
                link: "CLAUDE/Plan/00273-hook-input-payload-validation/PLAN.md"
            """)
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_active": True},
            allowlist=allowlist,
        )
        report = cic.scan(tmp_path)
        assert report.passed
        assert len(report.allowlisted) == 1

    def test_stale_allowlist_entry_is_a_violation(self, tmp_path: Path) -> None:
        allowlist = textwrap.dedent("""
            entries:
              - id: "unknown-input-field:Stop:no_such_read"
                reason: "gone"
                link: "CLAUDE/Plan/00273-hook-input-payload-validation/PLAN.md"
            """)
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
            allowlist=allowlist,
        )
        report = cic.scan(tmp_path)
        assert not report.passed
        assert report.violations[0].rule == "stale-allowlist-entry"

    def test_missing_contracts_dir_fails_fast(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            cic.scan(tmp_path)

    def test_core_reads_join_the_shared_surface(self, tmp_path: Path) -> None:
        # core/ holds genuine shared hook-payload readers (front_controller,
        # mode_interceptor, session_state, utils) — its reads are SHARED.
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
            core_source=(
                "def f(hook_input: dict):\n" '    return hook_input.get("core_only_field")\n'
            ),
        )
        report = cic.scan(tmp_path)
        assert not report.passed
        finding = report.violations[0]
        assert finding.event == cic.SHARED_SURFACE
        assert finding.subject == "core_only_field"

    def test_malformed_allowlist_entry_missing_reason(self, tmp_path: Path) -> None:
        allowlist = textwrap.dedent("""
            entries:
              - id: "unknown-input-field:Stop:stop_hook_active"
                link: "CLAUDE/Plan/00273-hook-input-payload-validation/PLAN.md"
            """)
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_active": True},
            allowlist=allowlist,
        )
        report = cic.scan(tmp_path)
        assert any(f.rule == "malformed-allowlist-entry" for f in report.violations)

    def test_malformed_allowlist_entry_missing_link(self, tmp_path: Path) -> None:
        allowlist = textwrap.dedent("""
            entries:
              - id: "unknown-input-field:Stop:stop_hook_active"
                reason: "reason without a link"
            """)
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_active": True},
            allowlist=allowlist,
        )
        report = cic.scan(tmp_path)
        assert any(f.rule == "malformed-allowlist-entry" for f in report.violations)

    def test_scan_report_carries_read_surface_and_skipped_events(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        src = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers" / "notification"
        src.mkdir(parents=True)
        (src / "h.py").write_text(
            'def f(hook_input: dict):\n    return hook_input.get("message")\n'
        )
        report = cic.scan(tmp_path)
        assert report.passed  # Notification has no vendored example here: skipped
        assert "Stop" in report.read_surface
        assert report.skipped_events == ["Notification"]

    def test_malformed_contract_json_missing_event_key(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        contracts = tmp_path / "contracts" / "claude-code-hooks"
        (contracts / "Broken.json").write_text(json.dumps({"input_example": {}}))
        with pytest.raises(ValueError, match="Broken.json"):
            cic.scan(tmp_path)


# ── the real tree ─────────────────────────────────────────────────


class TestRealTree:
    def test_real_repository_is_green(self) -> None:
        report = cic.scan(_SCRIPTS_QA_DIR.parent.parent)
        assert report.passed, [f.message for f in report.violations]

    def test_real_inventory_excludes_status_line_and_nitpick(self) -> None:
        reads = cic.collect_read_surface(_SCRIPTS_QA_DIR.parent.parent)
        assert "StatusLine" not in reads
        for key in reads:
            assert "nitpick" not in key.lower()


# ── CLI ───────────────────────────────────────────────────────────


class TestMain:
    def test_main_green_exit_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        assert cic.main(["--root", str(tmp_path)]) == 0
        assert "No input-contract violations" in capsys.readouterr().out

    def test_main_violation_exit_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"other": True},
        )
        assert cic.main(["--root", str(tmp_path)]) == 1
        assert "stop_hook_active" in capsys.readouterr().out

    def test_main_json_artifact(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        assert cic.main(["--root", str(tmp_path), "--json"]) == 0
        artifact = tmp_path / "untracked" / "qa" / "input_contract.json"
        data = json.loads(artifact.read_text())
        assert data["summary"]["passed"] is True

    def test_main_malformed_contract_exit_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        contracts = tmp_path / "contracts" / "claude-code-hooks"
        (contracts / "Broken.json").write_text(json.dumps({"input_example": {}}))
        assert cic.main(["--root", str(tmp_path)]) == 2
        assert "Broken.json" in capsys.readouterr().err

    def test_main_report_stdout_prints_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        assert cic.main(["--root", str(tmp_path), "--report-stdout"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["summary"]["passed"] is True

    def test_main_inventory_lists_skipped_events(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        pkg = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers" / "notification"
        pkg.mkdir(parents=True)
        (pkg / "h.py").write_text(
            'def f(hook_input: dict):\n    return hook_input.get("message")\n'
        )
        assert cic.main(["--root", str(tmp_path), "--inventory"]) == 0
        out = capsys.readouterr().out
        assert "Notification" in out
        assert "no vendored input example" in out

    def test_main_inventory_lists_read_surface(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tree(
            tmp_path,
            handler_source=_CLEAN_HANDLER,
            stop_example={"stop_hook_active": True},
        )
        assert cic.main(["--root", str(tmp_path), "--inventory"]) == 0
        out = capsys.readouterr().out
        assert "Stop" in out
        assert "stop_hook_active" in out
