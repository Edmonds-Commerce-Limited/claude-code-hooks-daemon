"""Comparing forwarders must not assert where the checkout happens to live.

`test_hook_scripts_match_installer` compares the tracked `.claude/hooks/*`
against a fresh generation, byte for byte. Its docstring names three purposes —
the installer creates correct scripts, no manual edit has drifted, and script
updates reach the installer code. **The absolute project root is an INPUT to
the generator, not part of the template any of those three is about.**

Comparing it verbatim additionally asserts "this checkout sits at the same
absolute path as the machine that generated the committed file", which is false
everywhere but one box — so the test passed here and failed on every CI runner
(Plan 00250 Task 2.4c).

Measured before choosing a fix: of 1342 lines across the 31 tracked hook files,
**54 carry the generating machine's root, and they are 2 distinct lines** in 27
files. A surface that small can be normalised without blunting the comparison —
every other byte is still compared exactly, and `surviving_absolute_paths`
asserts no OTHER machine-specific absolute path survives it.

**That is necessary and not sufficient, and the guard is what proved it.** See
`TestALongRootChangesTheGuardsSHAPE`: a runner-length checkout crosses the
AF_UNIX 108-byte limit and takes a different branch of the generator, so its
forwarders differ from these in shape rather than in a literal. The measurement
above was taken on the one machine that cannot exhibit that branch.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.install.forwarder_generator import (
    PROJECT_ROOT_PLACEHOLDER,
    normalise_project_root,
    surviving_absolute_paths,
)

_ROOT = "/workspace"
_OTHER_ROOT = "/home/runner/work/claude-code-hooks-daemon/claude-code-hooks-daemon"

_GUARD = '_rl_dir="{root}/untracked"\n_rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{root}/untracked/bin/hooks-relay}}"\n'


class TestNormalisingTheRoot:
    def test_two_checkouts_of_the_same_template_compare_equal(self) -> None:
        """The property the whole fix rests on."""
        here = normalise_project_root(_GUARD.format(root=_ROOT), _ROOT)
        there = normalise_project_root(_GUARD.format(root=_OTHER_ROOT), _OTHER_ROOT)
        assert here == there

    def test_the_placeholder_actually_replaces_the_root(self) -> None:
        normalised = normalise_project_root(_GUARD.format(root=_ROOT), _ROOT)
        assert _ROOT not in normalised
        assert PROJECT_ROOT_PLACEHOLDER in normalised

    def test_a_genuine_template_difference_still_shows(self) -> None:
        """Normalisation must not blunt the comparison it enables."""
        drifted = _GUARD.format(root=_ROOT).replace("_rl_dir", "_rl_directory")
        assert normalise_project_root(drifted, _ROOT) != normalise_project_root(
            _GUARD.format(root=_ROOT), _ROOT
        )

    def test_content_without_the_root_is_returned_unchanged(self) -> None:
        untouched = "#!/bin/bash\nexec python3 -m thing\n"
        assert normalise_project_root(untouched, _ROOT) == untouched

    def test_a_trailing_slash_on_the_root_does_not_leak_through(self) -> None:
        """A root passed with a trailing slash must normalise identically."""
        content = _GUARD.format(root=_ROOT)
        assert normalise_project_root(content, _ROOT + "/") == normalise_project_root(
            content, _ROOT
        )


class TestNothingElseIsMachineSpecific:
    """The second guard: normalising one path must not hide a second one."""

    def test_a_surviving_absolute_path_is_reported(self) -> None:
        content = normalise_project_root(
            _GUARD.format(root=_ROOT) + '_other="/home/someone/.cargo/bin/tool"\n', _ROOT
        )
        assert "/home/someone/.cargo/bin/tool" in surviving_absolute_paths(content)

    def test_the_normalised_guard_leaves_nothing_behind(self) -> None:
        assert not surviving_absolute_paths(
            normalise_project_root(_GUARD.format(root=_ROOT), _ROOT)
        )

    @pytest.mark.parametrize(
        "line",
        [
            "exec /usr/bin/env python3",
            'PY="/bin/sh"',
            "# see /etc/hosts",
            "#!/bin/bash",
        ],
    )
    def test_system_paths_are_not_machine_specific(self, line: str) -> None:
        """A forwarder legitimately names system paths; those are portable."""
        assert not surviving_absolute_paths(line)

    @pytest.mark.parametrize(
        "line",
        [
            # A variable expansion whose TAIL merely looks absolute.
            '_rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"',
            'source "$SCRIPT_DIR/../init.sh"',
            # A relative path inside a comment.
            "# changes are discarded. See CLAUDE/LLM-INSTALL.md",
            # A substitution PATTERN, not a path.
            '_rl_sfx="${_rl_sfx// /-}"',
        ],
    )
    def test_ordinary_shell_is_not_mistaken_for_an_absolute_path(self, line: str) -> None:
        """Each of these was reported as machine-specific by a naive matcher.

        They are real lines from this repo's own forwarders. A guard that cries
        wolf on them would be switched off, which is worse than not having it.
        """
        assert not surviving_absolute_paths(line)

    def test_a_default_value_expansion_still_exposes_a_baked_path(self) -> None:
        """The one shape that MUST stay detected: `${VAR:-/abs/path}`.

        It is exactly how the relay binary path is baked, so a rule that
        excluded it would miss the very thing this guard is for.
        """
        line = '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/home/runner/untracked/bin/hooks-relay}"'
        assert surviving_absolute_paths(line) == ["/home/runner/untracked/bin/hooks-relay"]


class TestALongRootChangesTheGuardsSHAPE:
    """Normalising the root is necessary and NOT sufficient — proven here.

    Written to assert "the guard differs only by the project root", which is
    what the 2-distinct-lines measurement suggested. It is false, and the
    second guard above is what caught it on its first real run.

    `build_relay_guard_block` has two branches. Normally the events directory is
    computed dynamically in bash (`$_rl_dir/events$_rl_sfx`), so only the root is
    baked. But when that dynamic path would exceed the AF_UNIX 108-byte limit,
    the function bakes the daemon's resolved fallback directory instead — a
    SECOND absolute path, and a structurally different block.

    `/workspace` is 10 characters and takes the dynamic branch. A GitHub
    runner's checkout is 67 and takes the fallback branch. So the tracked
    forwarders and a runner's regeneration differ in shape, not merely in a
    literal, and no amount of root-normalisation reconciles them — they are
    different correct outputs for different machines (Plan 00250 Task 2.4c).
    """

    @staticmethod
    def _guard_at(root: str) -> str:
        from pathlib import Path

        from claude_code_hooks_daemon.config.models import TransportConfig
        from claude_code_hooks_daemon.install.forwarder_generator import (
            build_relay_guard_block,
        )

        return build_relay_guard_block("pre-tool-use", TransportConfig(), Path(root) / "untracked")

    def test_a_short_root_bakes_only_the_root(self) -> None:
        normalised = normalise_project_root(self._guard_at(_ROOT), _ROOT)
        assert not surviving_absolute_paths(normalised)
        assert "$_rl_dir/events" in normalised, "expected the dynamic events branch"

    def test_a_runner_length_root_bakes_a_second_absolute_path(self) -> None:
        """The finding: root-normalisation alone cannot make CI compare equal."""
        normalised = normalise_project_root(self._guard_at(_OTHER_ROOT), _OTHER_ROOT)
        surviving = surviving_absolute_paths(normalised)
        assert surviving, (
            "a runner-length checkout takes the AF_UNIX fallback branch, which "
            "bakes the resolved events directory as a literal — so the guard "
            "block differs from a short-root one in shape, not just in the root"
        )
        assert all(path.startswith("/") for path in surviving)

    def test_the_two_roots_take_different_branches(self) -> None:
        """States the cause, so a future reader need not rediscover it."""
        assert "$_rl_dir/events" in self._guard_at(_ROOT)
        assert "$_rl_dir/events" not in self._guard_at(_OTHER_ROOT)
