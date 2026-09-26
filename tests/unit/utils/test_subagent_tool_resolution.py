"""Tests for the shared subagent Write-capability resolver (Plan 00460).

`subagent_report_size_blocker` and `dispatch_declaration` both need to know
whether a dispatched/stopping `agent_type` can create a NEW file via `Write`,
so there is ONE resolver (Task 1.1) rather than two subtly different guesses.

Resolution order, each documented with its own test class below (review
M4: PROJECT/USER before built-in, since a project/user agent can OVERRIDE
a built-in of the same name -- see TestManagedOverridePrecedence):

1. Project agents (`<project_root>/.claude/agents/**/*.md`) — frontmatter
   `tools`/`disallowedTools`, matched by the `name:` field per the doc
   ("identity comes only from the `name` frontmatter field"), not filename.
2. User agents (`<config_dir>/agents/**/*.md`, the config dir being
   `$CLAUDE_CONFIG_DIR` or `~/.claude`) — same rule.
3. Built-in types — a small constant table, cited against the vendored
   `remote-docs/code.claude.com/docs/en/sub-agents.md` doc. A built-in whose
   tools the doc does NOT enumerate (`claude-code-guide`, `statusline-setup`)
   resolves to unknown (``None``) rather than being guessed.
4. Plugin agents (Plan 00468) — an enabled plugin's agent, by its scoped id.
5. Anything else (a managed-settings override, a type matching nothing
   above) — unknown.

Frontmatter that strict YAML rejects falls back to a lenient parser (Plan
00468 P6), and the whole definition is available through
``resolve_agent_definition`` (P7).

``None`` means "cannot resolve" and every caller must keep TODAY's
behaviour for it (fail-safe default), never treat it as either True or
False.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils.subagent_tool_resolution import (
    AgentSource,
    resolve_agent_can_write,
    resolve_agent_definition,
    resolve_lookup_root,
)
from tests.claude_plugin_fixture import READ_ONLY_TOOLS, install_fake_plugin


@pytest.fixture(autouse=True)
def _hermetic_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that passes no ``config_dir`` must still never read the real
    Claude home: point the default at an empty directory."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "default-config"))


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


class TestManagedOverridePrecedence:
    """Review M4: the vendored doc (remote-docs/code.claude.com/docs/en/
    sub-agents.md:55) states 'A user or project subagent named Explore
    overrides the built-in' -- so project/user agents must be consulted
    BEFORE the built-in table, not after. The prior order failed towards
    READ-ONLY for a project's own writable `Explore` override, which is
    the opposite of this module's own documented fail-safe contract
    ('unknown, keep today's behaviour')."""

    def test_a_project_explore_override_with_write_resolves_writable(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "explore.md",
            "name: Explore\ndescription: project override\ntools: Read, Write, Bash",
        )
        assert resolve_agent_can_write("Explore", tmp_path) is True

    def test_a_project_explore_override_with_no_tools_line_inherits_write(
        self, tmp_path: Path
    ) -> None:
        """The doc's own recommended shape for overriding Explore: no
        `tools:` line at all, which inherits every tool including Write."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "explore.md",
            "name: Explore\ndescription: project override, inherits everything\nmodel: haiku",
        )
        assert resolve_agent_can_write("Explore", tmp_path) is True

    def test_a_project_plan_override_without_write_still_reads_as_read_only(
        self, tmp_path: Path
    ) -> None:
        """A project override that keeps the built-in's own read-only shape
        must still resolve read-only -- the fix is about PRECEDENCE, not
        about always answering True."""
        _write_agent(
            tmp_path / ".claude" / "agents",
            "plan.md",
            "name: Plan\ndescription: project override, still read-only\ntools: Read, Grep",
        )
        assert resolve_agent_can_write("Plan", tmp_path) is False

    def test_builtin_table_still_answers_when_no_override_exists(self, tmp_path: Path) -> None:
        """No project/user agent named Explore anywhere -- falls through to
        the built-in table exactly as before."""
        assert resolve_agent_can_write("Explore", tmp_path) is False


class TestUserAgents:
    def test_user_agent_without_write_is_read_only(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        config_dir = tmp_path / "config"
        _write_agent(
            config_dir / "agents",
            "personal-reviewer.md",
            "name: personal-reviewer\ndescription: user-scoped\ntools: Read, Grep",
        )
        assert (
            resolve_agent_can_write("personal-reviewer", project_root, config_dir=config_dir)
            is False
        )

    def test_project_agent_takes_precedence_over_user_agent(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        config_dir = tmp_path / "config"
        _write_agent(
            project_root / ".claude" / "agents",
            "shared-name.md",
            "name: shared-name\ndescription: project scoped\ntools: Read, Write",
        )
        _write_agent(
            config_dir / "agents",
            "shared-name.md",
            "name: shared-name\ndescription: user scoped\ntools: Read",
        )
        assert resolve_agent_can_write("shared-name", project_root, config_dir=config_dir) is True

    def test_the_default_user_dir_honours_claude_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plan 00468 G13: user agents live under ``$CLAUDE_CONFIG_DIR/agents``,
        not a hard-coded ``~/.claude/agents``."""
        config_dir = tmp_path / "custom-config"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("HOME", str(tmp_path / "unused-home"))
        _write_agent(
            config_dir / "agents",
            "env-reviewer.md",
            "name: env-reviewer\ndescription: user-scoped\ntools: Read",
        )
        assert resolve_agent_can_write("env-reviewer", tmp_path / "project") is False


class TestLenientFrontmatter:
    """Plan 00468 P6: Claude Code loads an agent whose description holds
    ``: ``, which strict YAML rejects -- this repository's own
    ``code-reviewer.md`` is exactly that shape."""

    def test_a_colon_in_the_description_still_resolves_the_tools(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "code-reviewer.md",
            "name: code-reviewer\n"
            "description: Expert code review. Analyzes real quality issues: dead code\n"
            "tools: Read, Glob, Grep, Bash",
        )
        assert resolve_agent_can_write("code-reviewer", tmp_path) is False

    def test_this_repositorys_code_reviewer_resolves_read_only(self, tmp_path: Path) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        assert (repo_root / ".claude" / "agents" / "code-reviewer.md").is_file()
        assert (
            resolve_agent_can_write("code-reviewer", repo_root, config_dir=tmp_path / "config")
            is False
        )


def _plugin_project(
    tmp_path: Path, agents: dict[str, str | None], *, enable_in: str | None = "local"
) -> tuple[Path, Path]:
    """A project with one fake DBF-shaped plugin; returns (project, config)."""
    project_root = tmp_path / "project"
    (project_root / ".claude").mkdir(parents=True)
    config_dir = tmp_path / "config"
    install_fake_plugin(config_dir, project_root, agents=agents, enable_in=enable_in)
    return project_root, config_dir


class TestPluginAgents:
    """Plan 00468 P2: plugin agents resolve through the enabled-plugins
    resolver, by their scoped id ``<plugin>[:<subdir>...]:<name>``."""

    def test_a_write_less_plugin_agent_is_read_only(self, tmp_path: Path) -> None:
        project, config = _plugin_project(
            tmp_path,
            {"conformance-reviewer.md": f"name: conformance-reviewer\ntools: {READ_ONLY_TOOLS}"},
        )
        assert (
            resolve_agent_can_write(
                "defence-before-fix:conformance-reviewer", project, config_dir=config
            )
            is False
        )

    def test_a_plugin_agent_with_write_can_write(self, tmp_path: Path) -> None:
        project, config = _plugin_project(
            tmp_path, {"writer.md": "name: writer\ntools: Read, Write"}
        )
        assert (
            resolve_agent_can_write("defence-before-fix:writer", project, config_dir=config) is True
        )

    def test_a_subfolder_agent_resolves_by_its_scoped_id(self, tmp_path: Path) -> None:
        project, config = _plugin_project(tmp_path, {"review/security.md": "tools: Read"})
        assert (
            resolve_agent_can_write(
                "defence-before-fix:review:security", project, config_dir=config
            )
            is False
        )

    def test_a_plugin_agent_with_no_frontmatter_inherits_every_tool(self, tmp_path: Path) -> None:
        """Claude Code ignores every field of a plugin agent whose frontmatter
        is missing, so no ``tools`` means the full inherited set."""
        project, config = _plugin_project(tmp_path, {"plain.md": None})
        assert (
            resolve_agent_can_write("defence-before-fix:plain", project, config_dir=config) is True
        )

    def test_a_disabled_plugin_is_unknown(self, tmp_path: Path) -> None:
        project, config = _plugin_project(
            tmp_path, {"r.md": "name: r\ntools: Read"}, enable_in=None
        )
        settings = project / ".claude" / "settings.local.json"
        settings.write_text('{"enabledPlugins": {"defence-before-fix@defence-before-fix": false}}')
        assert resolve_agent_can_write("defence-before-fix:r", project, config_dir=config) is None

    def test_an_unknown_scoped_id_is_unknown(self, tmp_path: Path) -> None:
        project, config = _plugin_project(tmp_path, {"r.md": "name: r\ntools: Read"})
        assert (
            resolve_agent_can_write("defence-before-fix:nothing", project, config_dir=config)
            is None
        )


class TestAgentDefinition:
    """Plan 00468 P7: callers get the whole definition, not only Write."""

    def test_a_plugin_definition_exposes_its_isolation(self, tmp_path: Path) -> None:
        project, config = _plugin_project(
            tmp_path,
            {"conformance-reviewer.md": "name: conformance-reviewer\nisolation: worktree"},
        )
        definition = resolve_agent_definition(
            "defence-before-fix:conformance-reviewer", project, config_dir=config
        )
        assert definition is not None
        assert definition.source is AgentSource.PLUGIN
        assert definition.isolation == "worktree"
        assert definition.declares_worktree_isolation is True

    def test_a_project_definition_exposes_its_frontmatter_and_path(self, tmp_path: Path) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "iso.md",
            "name: iso\ndescription: d\nisolation: Worktree\ntools: Read",
        )
        definition = resolve_agent_definition("iso", tmp_path, config_dir=tmp_path / "config")
        assert definition is not None
        assert definition.source is AgentSource.PROJECT
        assert definition.path == tmp_path / ".claude" / "agents" / "iso.md"
        assert definition.frontmatter["tools"] == "Read"
        assert definition.can_write is False
        assert definition.declares_worktree_isolation is True

    def test_no_isolation_field_is_none(self, tmp_path: Path) -> None:
        _write_agent(tmp_path / ".claude" / "agents", "a.md", "name: a\ndescription: d")
        definition = resolve_agent_definition("a", tmp_path, config_dir=tmp_path / "config")
        assert definition is not None
        assert definition.isolation is None
        assert definition.declares_worktree_isolation is False

    def test_a_builtin_definition_has_no_file(self, tmp_path: Path) -> None:
        definition = resolve_agent_definition("Explore", tmp_path, config_dir=tmp_path / "c")
        assert definition is not None
        assert definition.source is AgentSource.BUILTIN
        assert definition.path is None
        assert definition.can_write is False

    def test_an_unknown_type_has_no_definition(self, tmp_path: Path) -> None:
        assert resolve_agent_definition("nope", tmp_path, config_dir=tmp_path / "c") is None


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


class TestUnreadableAgentFileIsLogged:
    """Review m11: every OTHER fail-open site this plan added logs; the
    directory-scan loop's `except OSError: continue` was a bare skip.
    Portable without real permission bits (this suite can run as root,
    where chmod 000 does not actually deny root): monkeypatch `read_text`
    to raise for the specific candidate file."""

    def test_an_unreadable_file_is_skipped_and_logged_at_debug(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_agent(
            tmp_path / ".claude" / "agents",
            "broken.md",
            "name: broken\ndescription: this file will fail to read\ntools: Read",
        )

        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            with caplog.at_level(logging.DEBUG):
                result = resolve_agent_can_write("broken", tmp_path)

        assert result is None
        assert any(record.levelno == logging.DEBUG for record in caplog.records)
