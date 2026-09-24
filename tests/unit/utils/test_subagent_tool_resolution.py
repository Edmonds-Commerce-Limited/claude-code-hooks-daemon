"""Tests for the shared subagent Write-capability resolver (Plan 00460).

`subagent_report_size_blocker` and `dispatch_declaration` both need to know
whether a dispatched/stopping `agent_type` can create a NEW file via `Write`,
so there is ONE resolver (Task 1.1) rather than two subtly different guesses.

Resolution order, each documented with its own test class below:

1. Built-in types — a small constant table, cited against the vendored
   `remote-docs/code.claude.com/docs/en/sub-agents.md` doc. A built-in whose
   tools the doc does NOT enumerate (`claude-code-guide`, `statusline-setup`)
   resolves to unknown (``None``) rather than being guessed.
2. Project agents (`<project_root>/.claude/agents/**/*.md`) — frontmatter
   `tools`/`disallowedTools`, matched by the `name:` field per the doc
   ("identity comes only from the `name` frontmatter field"), not filename.
3. User agents (`<home_dir>/.claude/agents/**/*.md`) — same rule.
4. Anything else (plugin agents, a type matching nothing above) — unknown.

``None`` means "cannot resolve" and every caller must keep TODAY's
behaviour for it (fail-safe default), never treat it as either True or
False.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.subagent_tool_resolution import (
    resolve_agent_can_write,
    resolve_lookup_root,
)


def _write_agent(agents_dir: Path, filename: str, frontmatter: str) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / filename).write_text(f"---\n{frontmatter}\n---\n\nBody.\n")


class TestBuiltinAgents:
    """Explore/Plan (read-only) and general-purpose/claude (writable) are
    documented directly in the vendored sub-agents.md 'Built-in subagents'
    section -- see the journal (T1.1 finding) for the exact quoted lines."""

    def test_explore_is_read_only(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("Explore", tmp_path) is False

    def test_plan_is_read_only(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("Plan", tmp_path) is False

    def test_general_purpose_can_write(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("general-purpose", tmp_path) is True

    def test_claude_can_write(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("claude", tmp_path) is True

    def test_claude_code_guide_is_unknown(self, tmp_path: Path) -> None:
        """Upstream names it (model + trigger) but never enumerates its
        tools -- Task 1.1 requires a citation, so this stays unresolved
        rather than reusing the plan Overview's secondhand claim."""
        assert resolve_agent_can_write("claude-code-guide", tmp_path) is None

    def test_statusline_setup_is_unknown(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("statusline-setup", tmp_path) is None


class TestNoAgentType:
    def test_none_is_unknown(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write(None, tmp_path) is None

    def test_empty_string_is_unknown(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("", tmp_path) is None


class TestUnresolvableType:
    def test_unknown_name_with_no_matching_file_is_unknown(self, tmp_path: Path) -> None:
        assert resolve_agent_can_write("totally-invented-type", tmp_path) is None


class TestProjectAgents:
    def test_tools_list_without_write_is_read_only(self, tmp_path: Path) -> None:
        """Mirrors this project's real code-reviewer.md: tools: Read, Glob, Grep, Bash."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "code-reviewer.md",
            "name: code-reviewer\ndescription: reviews code\ntools: Read, Glob, Grep, Bash",
        )
        assert resolve_agent_can_write("code-reviewer", tmp_path) is False

    def test_tools_list_with_write_can_write(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "editor.md",
            "name: editor\ndescription: edits code\ntools: Read, Write, Edit",
        )
        assert resolve_agent_can_write("editor", tmp_path) is True

    def test_absent_tools_field_inherits_everything(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "inherits.md",
            "name: inherits-all\ndescription: no tools field",
        )
        assert resolve_agent_can_write("inherits-all", tmp_path) is True

    def test_disallowed_tools_removes_write_from_inherited_set(self, tmp_path: Path) -> None:
        """The doc's own worked example: disallowedTools: Write, Edit, no
        `tools` field -- inherits everything except the two removed."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "no-writes.md",
            "name: no-writes\ndescription: inherits except writes\ndisallowedTools: Write, Edit",
        )
        assert resolve_agent_can_write("no-writes", tmp_path) is False

    def test_disallowed_tools_without_write_leaves_inherited_write_intact(
        self, tmp_path: Path
    ) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "no-bash.md",
            "name: no-bash\ndescription: inherits except bash\ndisallowedTools: Bash",
        )
        assert resolve_agent_can_write("no-bash", tmp_path) is True

    def test_yaml_list_form_of_tools_is_parsed(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "list-form.md",
            "name: list-form\ndescription: yaml list\ntools:\n  - Read\n  - Grep",
        )
        assert resolve_agent_can_write("list-form", tmp_path) is False

    def test_disallowed_tools_specifier_is_stripped_before_matching(self, tmp_path: Path) -> None:
        """A `Bash(git push *)`-style specifier still names the whole tool;
        it must not be treated as a literal 'Write' near-miss or crash
        matching."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "specifier.md",
            "name: specifier\ndescription: has a specifier\ndisallowedTools: Bash(git push *)",
        )
        assert resolve_agent_can_write("specifier", tmp_path) is True

    def test_matched_by_name_field_not_filename(self, tmp_path: Path) -> None:
        """Per the doc: 'identity comes only from the name frontmatter
        field' -- the filename doesn't have to match."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "some-other-filename.md",
            "name: real-name\ndescription: filename does not match name\ntools: Read",
        )
        assert resolve_agent_can_write("real-name", tmp_path) is False

    def test_nested_subfolder_is_scanned_recursively(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents" / "review",
            "security.md",
            "name: nested-reviewer\ndescription: lives in a subfolder\ntools: Read",
        )
        assert resolve_agent_can_write("nested-reviewer", tmp_path) is False

    def test_malformed_tools_field_is_unknown(self, tmp_path: Path) -> None:
        """A `tools:` value that is neither a string nor a list (e.g. a
        nested mapping) cannot be parsed safely -- unknown, not a guess."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "malformed.md",
            "name: malformed\ndescription: bad tools field\ntools:\n  nested: mapping",
        )
        assert resolve_agent_can_write("malformed", tmp_path) is None


class TestUserAgents:
    def test_home_agent_without_write_is_read_only(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        home_dir = tmp_path / "home"
        _write_agent(
            home_dir / ".claude" / "agents",
            "personal-reviewer.md",
            "name: personal-reviewer\ndescription: user-scoped\ntools: Read, Grep",
        )
        assert (
            resolve_agent_can_write("personal-reviewer", project_root, home_dir=home_dir) is False
        )

    def test_project_agent_takes_precedence_over_home_agent(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        home_dir = tmp_path / "home"
        _write_agent(
            project_root / ".claude" / "agents",
            "shared-name.md",
            "name: shared-name\ndescription: project scoped\ntools: Read, Write",
        )
        _write_agent(
            home_dir / ".claude" / "agents",
            "shared-name.md",
            "name: shared-name\ndescription: user scoped\ntools: Read",
        )
        assert resolve_agent_can_write("shared-name", project_root, home_dir=home_dir) is True


class TestResolveLookupRoot:
    """Shared by every handler that calls ``resolve_agent_can_write`` (Plan
    00460): a test override wins, then the registry's ``workspace_root``
    option, then :func:`resolve_project_root`, then the process cwd."""

    def test_project_root_override_wins(self, tmp_path: Path) -> None:
        override = tmp_path / "override"
        assert resolve_lookup_root(override, tmp_path / "workspace") == override

    def test_workspace_root_used_when_no_override(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        assert resolve_lookup_root(None, workspace) == workspace

    def test_falls_back_to_cwd_when_nothing_else_resolves(self) -> None:
        # ProjectContext is not initialised in a bare unit test, so
        # resolve_project_root() returns None and this falls all the way
        # through to the process cwd.
        assert resolve_lookup_root(None, None) == Path.cwd()
