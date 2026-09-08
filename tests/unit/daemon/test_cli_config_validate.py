"""Tests for the `config-validate` CLI verb and the skill-text verb contract.

Plan 00362 Task 1.7 (client report section 7): a client's skill routed
`validate-config` to a CLI that only knew `config-validate`, and the CLI
demanded a positional config path the skill did not pass. Both halves are
closed here -- the verb is accepted under either spelling, the path defaults
to the project's own config -- and a sweep asserts that every verb the
deployed skill text forwards to the daemon CLI is one the parser accepts,
so the two surfaces cannot drift apart again without a test noticing.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import claude_code_hooks_daemon
from claude_code_hooks_daemon.daemon.cli import main

_PACKAGE_ROOT = Path(claude_code_hooks_daemon.__file__).parent
_SKILL_DIR = _PACKAGE_ROOT / "skills" / "hooks-daemon"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_DAEMON_CLI_SH = _SKILL_DIR / "scripts" / "daemon-cli.sh"

# A `case` arm: leading whitespace, one or more `|`-separated words, `)`.
_CASE_ARM = re.compile(r"^\s+([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)*)\)\s*$")
# The forwarding line inside an arm. Group 1 is what follows the wrapper
# path: either a literal verb or the `"$SUBCOMMAND"` pass-through.
_FORWARD = re.compile(r'daemon-cli\.sh"\s+(\S+)')
# The wrapper's own header examples: `#   ./daemon-cli.sh <verb>`.
_WRAPPER_EXAMPLE = re.compile(r"^#\s+\./daemon-cli\.sh\s+([a-z][a-z0-9-]*)\s*$")


def _parser_accepts(verb: str) -> bool:
    """True when argparse recognises ``verb`` as a subcommand.

    ``--help`` on a known subcommand exits 0 before any command body runs;
    an unknown choice is rejected by the top-level parser with exit 2.
    """
    with patch("sys.argv", ["claude-hooks-daemon", verb, "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code == 0


def _verbs_routed_by_skill_text() -> set[str]:
    """Every CLI verb the skill's `case` block hands to daemon-cli.sh."""
    verbs: set[str] = set()
    lines = _SKILL_MD.read_text().splitlines()
    for index, line in enumerate(lines):
        arm = _CASE_ARM.match(line)
        if arm is None:
            continue
        # Look at the arm body up to the next `;;` for a forwarding line.
        body: list[str] = []
        for body_line in lines[index + 1 :]:
            if body_line.strip() == ";;":
                break
            body.append(body_line)
        for body_line in body:
            forward = _FORWARD.search(body_line)
            if forward is None:
                continue
            target = forward.group(1)
            if target == '"$SUBCOMMAND"':
                verbs.update(arm.group(1).split("|"))
            else:
                verbs.add(target)
    return verbs


def _verbs_in_wrapper_examples() -> set[str]:
    return {
        match.group(1)
        for line in _DAEMON_CLI_SH.read_text().splitlines()
        if (match := _WRAPPER_EXAMPLE.match(line)) is not None
    }


class TestConfigValidateVerb:
    """`config-validate` and its alias, with and without a path."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        claude_dir = tmp_path / ".claude"
        (claude_dir / "hooks-daemon").mkdir(parents=True)
        (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n")
        return tmp_path

    def test_canonical_verb_is_accepted(self) -> None:
        assert _parser_accepts("config-validate")

    def test_validate_config_alias_is_accepted(self) -> None:
        assert _parser_accepts("validate-config")

    def test_alias_dispatches_to_the_same_command(self, project: Path) -> None:
        config_path = project / ".claude" / "hooks-daemon.yaml"
        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "validate-config", str(config_path)],
            ),
            patch(
                "claude_code_hooks_daemon.install.config_cli.run_config_validate",
                return_value={"valid": True, "errors": []},
            ) as run,
        ):
            assert main() == 0
        run.assert_called_once_with(config_path=config_path)

    def test_config_path_defaults_to_the_project_config(self, project: Path) -> None:
        """No positional path: the project's own config is validated.

        Project detection itself (git remote, nested-install checks) is
        `get_project_path`'s contract and tested there; here it is stubbed
        so the assertion is only about the default the verb derives.
        """
        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(project), "config-validate"],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=project,
            ) as detect,
            patch(
                "claude_code_hooks_daemon.install.config_cli.run_config_validate",
                return_value={"valid": True, "errors": []},
            ) as run,
        ):
            assert main() == 0
        detect.assert_called_once_with(project)
        run.assert_called_once_with(config_path=project / ".claude" / "hooks-daemon.yaml")

    def test_explicit_config_path_still_wins(self, project: Path, tmp_path: Path) -> None:
        other = tmp_path / "other.yaml"
        other.write_text("version: '1.0'\n")
        with (
            patch(
                "sys.argv",
                [
                    "claude-hooks-daemon",
                    "--project-root",
                    str(project),
                    "config-validate",
                    str(other),
                ],
            ),
            patch(
                "claude_code_hooks_daemon.install.config_cli.run_config_validate",
                return_value={"valid": False, "errors": ["x"]},
            ) as run,
        ):
            assert main() == 1
        run.assert_called_once_with(config_path=other)


class TestSkillTextRoutesOnlyKnownVerbs:
    """Every verb the deployed skill forwards must be one the CLI parses."""

    def test_skill_case_arms_were_found(self) -> None:
        """Guard against the regexes silently matching nothing."""
        verbs = _verbs_routed_by_skill_text()
        assert {"status", "restart", "config-validate", "explain-rule"} <= verbs

    def test_every_skill_routed_verb_is_accepted_by_the_parser(self) -> None:
        rejected = sorted(
            verb for verb in _verbs_routed_by_skill_text() if not _parser_accepts(verb)
        )
        assert rejected == [], f"SKILL.md routes verbs the CLI rejects: {rejected}"

    def test_skill_routes_the_validate_config_alias(self) -> None:
        """The spelling the client typed must reach the CLI, not the help text."""
        assert "validate-config" in _verbs_routed_by_skill_text()

    def test_every_wrapper_example_verb_is_accepted_by_the_parser(self) -> None:
        examples = _verbs_in_wrapper_examples()
        assert examples, "daemon-cli.sh header examples not found"
        rejected = sorted(verb for verb in examples if not _parser_accepts(verb))
        assert rejected == [], f"daemon-cli.sh examples name verbs the CLI rejects: {rejected}"

    def test_deployed_skill_copy_matches_the_package_source(self) -> None:
        """The repo's own deployed skill is the package's skill, byte for byte."""
        deployed = _PACKAGE_ROOT.parent.parent / ".claude" / "skills" / "hooks-daemon" / "SKILL.md"
        if not deployed.exists():
            pytest.skip("not a self-install checkout")
        assert deployed.read_text() == _SKILL_MD.read_text()
