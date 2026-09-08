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

The first attempt normalised the root on both sides. Measured, that looked
sufficient: of 1342 lines across the 31 tracked hook files, 54 carry the
generating machine's root and they are 2 distinct lines in 27 files.

**It was necessary and not sufficient, and `surviving_absolute_paths` — added
only as a "don't let this hide a second path" guard — is what proved it.** See
`TestALongRootChangesTheGuardsSHAPE`: a runner-length checkout crosses the
AF_UNIX 108-byte limit and takes a *different branch* of the generator, so its
forwarders differ in shape, not in a literal. The measurement had been taken on
the one machine that cannot exhibit that branch.

**The fix is `recorded_untracked_dir`**: regenerate for the root the deployed
forwarders themselves record, so the comparison is byte-exact everywhere and
normalisation is not needed for it at all. The remaining variable is the
hostname, which the branch decision also consults —
`TestTheRecordedRootIsHostnameIndependentInPractice` measures that rather than
assuming it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.forwarder_generator import (
    PROJECT_ROOT_PLACEHOLDER,
    normalise_project_root,
    recorded_untracked_dir,
    surviving_absolute_paths,
    unexpected_absolute_paths,
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


class TestReadingTheRootTheTrackedFilesRecord:
    """The fix Task 2.4c actually needs: regenerate at the RECORDED root.

    Each generated forwarder states the untracked dir it was built for, in
    `_rl_dir="..."`. Regenerating at THAT root rather than at the current
    checkout's makes the comparison exact on any machine, with no normalisation
    — and tests all three of the comparison's stated purposes, none of which is
    about where this checkout happens to live.

    Safe because the short recorded root keeps the generator on its dynamic
    branch anywhere: 54 characters of hostname-suffix headroom against a 64-char
    OS cap (see RESEARCH-ci-failures.md).
    """

    def test_it_reads_the_dir_out_of_a_guard_block(self) -> None:
        assert recorded_untracked_dir({"pre-tool-use": _GUARD.format(root=_ROOT)}) == Path(
            "/workspace/untracked"
        )

    def test_files_without_a_guard_are_ignored_not_fatal(self) -> None:
        """`status-line`, `stop`, `subagent-stop`, `worktree-create` carry none."""
        contents = {
            "pre-tool-use": _GUARD.format(root=_ROOT),
            "stop": "#!/bin/bash\nexec thing\n",
        }
        assert recorded_untracked_dir(contents) == Path("/workspace/untracked")

    def test_no_guard_anywhere_returns_none(self) -> None:
        """Relay disabled: there is no recorded root, so the caller falls back."""
        assert recorded_untracked_dir({"stop": "#!/bin/bash\n"}) is None

    def test_disagreeing_files_are_an_error(self) -> None:
        """Closes the hole: a hand-edited `_rl_dir` must not be regenerated to match."""
        contents = {
            "pre-tool-use": _GUARD.format(root=_ROOT),
            "post-tool-use": _GUARD.format(root=_OTHER_ROOT),
        }
        with pytest.raises(AssertionError, match="disagree"):
            recorded_untracked_dir(contents)

    def test_the_real_tracked_forwarders_agree_on_one_root(self) -> None:
        """Over the actual repository, not a fixture."""
        hooks_dir = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
        contents = {
            path.name: path.read_text(encoding="utf-8")
            for path in hooks_dir.iterdir()
            if path.is_file() and not path.name.endswith(".bak")
        }
        recorded = recorded_untracked_dir(contents)
        assert recorded is not None
        assert recorded.name == "untracked"


class TestTheRecordedRootIsHostnameIndependentInPractice:
    """The runner condition, reproduced rather than reasoned about.

    Generating for the recorded root removes the checkout path as a variable,
    but the branch decision also consults the HOSTNAME — so "machine-independent"
    had to be measured, not asserted. It holds to a hostname of about 40
    characters and breaks at 53, which matches the arithmetic: 54 characters of
    headroom against the AF_UNIX limit.

    A GitHub runner hostname (`fv-az1234-567`, 13 characters) is nowhere near it.
    """

    _RECORDED = Path("/workspace/untracked")

    def _guard(self) -> str:
        from claude_code_hooks_daemon.config.models import TransportConfig
        from claude_code_hooks_daemon.install.forwarder_generator import (
            build_relay_guard_block,
        )

        return build_relay_guard_block("user-prompt-expansion", TransportConfig(), self._RECORDED)

    @pytest.mark.parametrize(
        ("hostname", "label"),
        [("a", "minimal"), ("fv-az1234-567", "a GitHub runner"), ("x" * 40, "40 chars")],
    )
    def test_the_output_does_not_change_with_the_hostname(
        self, monkeypatch: pytest.MonkeyPatch, hostname: str, label: str
    ) -> None:
        monkeypatch.setenv("HOSTNAME", "reference-host")
        reference = self._guard()
        monkeypatch.setenv("HOSTNAME", hostname)
        assert self._guard() == reference, f"output changed for {label}"

    def test_the_breaking_point_is_where_the_arithmetic_says(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vacuity, and a warning: this is not hostname-proof, just proof enough.

        `user-prompt-expansion` is the longest wired event name and so sets the
        budget. Adding a longer one eats the same headroom.
        """
        monkeypatch.setenv("HOSTNAME", "reference-host")
        reference = self._guard()
        monkeypatch.setenv("HOSTNAME", "y" * 53)
        assert self._guard() != reference


class TestTheGuardJudgesTheBAKEDRootNotTheLIVEOne:
    """The same mistake, one level up — caught by the guard itself on CI.

    `test_no_other_machine_specific_path_survives` normalised the tracked
    forwarders against `get_project_root()`, the LIVE checkout. On the machine
    that generated them those two roots are the same string, so the difference
    was invisible; on a runner they differ and every baked path was reported as
    a second machine-specific path.

    So the guard must be told which roots the artefact BAKES, and judge what is
    left over — the same correction Task 2.4c made to the comparison it guards.
    """

    _BAKED = "/workspace"
    _LIVE = _OTHER_ROOT

    def _content(self) -> str:
        return _GUARD.format(root=self._BAKED)

    def test_a_baked_root_is_not_reported_when_it_is_declared(self) -> None:
        assert not unexpected_absolute_paths(self._content(), [self._BAKED])

    def test_judging_against_the_live_root_alone_is_what_failed_on_ci(self) -> None:
        """Pins the defect, so a revert cannot pass quietly."""
        assert unexpected_absolute_paths(self._content(), [self._LIVE]) == [
            f"{self._BAKED}/untracked",
            f"{self._BAKED}/untracked/bin/hooks-relay",
        ]

    def test_declaring_both_roots_is_what_the_caller_actually_does(self) -> None:
        """The live checkout stays declared: on one machine it IS the baked one."""
        assert not unexpected_absolute_paths(self._content(), [self._LIVE, self._BAKED])

    def test_a_root_nested_inside_another_is_stripped_whole(self) -> None:
        """`untracked` sits under the root, so the two declared roots overlap.

        Replacing the shorter one first would leave the longer one's tail
        looking like a fresh absolute path.
        """
        assert not unexpected_absolute_paths(
            self._content(), [self._BAKED, f"{self._BAKED}/untracked"]
        )

    def test_an_undeclared_path_is_still_reported(self) -> None:
        """The guard must not be turned off by the fix that made it portable."""
        content = self._content() + '_other="/home/someone/.cargo/bin/tool"\n'
        assert unexpected_absolute_paths(content, [self._BAKED]) == [
            "/home/someone/.cargo/bin/tool"
        ]

    def test_no_declared_roots_reports_every_absolute_path(self) -> None:
        assert unexpected_absolute_paths(self._content(), []) == [
            f"{self._BAKED}/untracked",
            f"{self._BAKED}/untracked/bin/hooks-relay",
        ]

    def test_the_real_tracked_forwarders_are_clean_from_a_FOREIGN_checkout(self) -> None:
        """The CI failure itself, reproduced against the real artefact.

        Runs the guard over the tracked forwarders while claiming to live
        somewhere they were not generated — which is every machine but this
        one. Judging locally proves nothing here: the two roots coincide, and
        that coincidence is what hid the defect until a runner found it.
        """
        hooks_dir = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
        contents = {
            path.name: path.read_text(encoding="utf-8")
            for path in hooks_dir.iterdir()
            if path.is_file() and not path.name.endswith(".bak")
        }
        recorded = recorded_untracked_dir(contents)
        assert recorded is not None, "the tracked forwarders record no root to judge against"

        offenders = {
            name: unexpected
            for name, content in contents.items()
            if (unexpected := unexpected_absolute_paths(content, [_OTHER_ROOT, str(recorded)]))
        }
        assert not offenders
