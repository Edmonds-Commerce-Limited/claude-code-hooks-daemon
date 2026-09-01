"""Tests for `_collect_enforcement_status_lines` (Plan 00296 T4.1).

Surfaces downgraded handler enforcement (npm_command's llm-wrapper mode,
lint_on_edit's unresolvable extended linters, validate_eslint_on_write's
llm-wrapper mode) at `hooks-daemon check` time, evaluated at the repository
root and every `projects:`-declared root.
"""

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import _collect_enforcement_status_lines


class TestCollectEnforcementStatusLines:
    def test_no_config_falls_back_to_single_project_root(self, tmp_path: Path) -> None:
        """No `.claude/hooks-daemon.yaml` at all: still evaluates the repo root."""
        (tmp_path / ".claude").mkdir()
        statuses = _collect_enforcement_status_lines(tmp_path)
        # No package.json anywhere under tmp_path -> npm_command and
        # validate_eslint_on_write both report advisory-only at the root.
        assert any("npm_command" in s for s in statuses)
        assert any(str(tmp_path) in s for s in statuses)

    def test_nominal_when_llm_scripts_present(self, tmp_path: Path) -> None:
        """A package.json with an `llm:` script clears the npm_command advisory."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "true"}}), encoding="utf-8"
        )
        statuses = _collect_enforcement_status_lines(tmp_path)
        assert not any("npm_command" in s for s in statuses)
        assert not any("validate_eslint_on_write" in s for s in statuses)

    def test_declared_project_roots_are_each_evaluated(self, tmp_path: Path) -> None:
        """A `projects:` block adds each declared root to the evaluated set."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (tmp_path / "web").mkdir()
        (tmp_path / "web" / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "true"}}), encoding="utf-8"
        )
        (tmp_path / "infra").mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "projects:\n"
            "  - name: web\n"
            "    root: web\n"
            "  - name: infra\n"
            "    root: infra\n",
            encoding="utf-8",
        )
        statuses = _collect_enforcement_status_lines(tmp_path)
        # web declared llm: scripts -> its llm-wrapper probes are NOT degraded
        # (lint_on_edit's unrelated extended-linter probe may still report
        # there, so only the llm-wrapper handlers are asserted).
        assert not any(
            str(tmp_path / "web") in s and ("npm_command" in s or "validate_eslint" in s)
            for s in statuses
        )
        # infra has no package.json -> npm_command degraded there.
        assert any(str(tmp_path / "infra") in s and "npm_command" in s for s in statuses)

    def test_malformed_config_falls_back_rather_than_raising(self, tmp_path: Path) -> None:
        """`check` must survive a broken config -- it is also used to diagnose one."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text("not: [valid, yaml, :", encoding="utf-8")
        # Must not raise.
        statuses = _collect_enforcement_status_lines(tmp_path)
        assert isinstance(statuses, list)

    def test_returns_empty_list_when_every_probe_is_nominal(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "true"}}), encoding="utf-8"
        )
        from unittest.mock import patch

        # lint_on_edit's extended-linter probe is not deterministic across dev
        # environments (whether ruff/shellcheck/etc happen to be installed) --
        # pin it so this test asserts only the llm-wrapper probes.
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit."
            "LintOnEditHandler._resolve_executable",
            side_effect=lambda name, *_: name,
        ):
            statuses = _collect_enforcement_status_lines(tmp_path)
        assert statuses == []

    @pytest.mark.parametrize("expected_substring", ["npm_command", "validate_eslint_on_write"])
    def test_degraded_llm_wrapper_probes_name_the_handler(
        self, tmp_path: Path, expected_substring: str
    ) -> None:
        (tmp_path / ".claude").mkdir()
        statuses = _collect_enforcement_status_lines(tmp_path)
        assert any(expected_substring in s for s in statuses)
