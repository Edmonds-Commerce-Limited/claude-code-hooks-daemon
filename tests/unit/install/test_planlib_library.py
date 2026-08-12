"""Behavioural test suite for the deployed `_planlib.inc.bash` library.

Plan 00213 Phase 2. The library (`install/templates/_planlib.inc.bash`) was
independently re-verified statically in Phase 1 (see
`CLAUDE/Plan/00213-planlib-plan-folder-orchestrator-tooling/EVALUATION.md`
Sec.1): `bash -n` with an asserted-empty stderr, `shellcheck -x -S style`
clean, and a 24/24 defined-vs-called function cross-reference with zero
dangling or unused references. This suite is the RUNTIME/behavioural
counterpart that verification did not (and could not, from a static check)
cover -- it is the RED-then-GREEN test suite Phase 1 explicitly found
missing from the upstream proposal (PROPOSAL.md Sec.7 states four testing
*principles*, not a runnable file).

Four principles this suite follows (from PROPOSAL.md Sec.7 /
`CLAUDE/Plan/Cancelled/00199-hooks-daemon-plan-lib/PROPOSAL-ASSESSMENT.md`
Sec.8), all directly load-bearing for a library whose entire point is that
a control must not report success without doing its job (the incident in
PROPOSAL.md Sec.1.1):

1. Keep predicates pure and drive them through their real argument surface
   rather than mocking the shell around them (`_plan_fingerprint_present`,
   `_plan_strip_cr`, `_plan_find_repo_root` are all exercised as bash
   functions via subprocess, not re-implemented in Python).
2. Assert the MECHANISM, not just the exit code -- "returned 1" does not
   distinguish "refused correctly" from "crashed for an unrelated reason".
   Every guard test below also asserts the refusal message names the thing
   (e.g. "plan_gate_change", "BASH_SUBSHELL", "plan_mode deploy").
3. Every control gets a discriminating negative control. For a permanent
   regression suite (rather than the one-off manual perturbation Phase 1
   did by hand -- EVALUATION.md Sec.1.3, HUP-trap-removal /
   `set -o pipefail`-injection) this is expressed as an explicit WRONG-USAGE
   test paired with the RIGHT-USAGE test for every state-machine guard
   (mode mismatches, ordering enforcement, the BASH_SUBSHELL misuse guard):
   each pair proves the guard actually discriminates, not merely that it
   can be made to fire.
4. State what this suite does NOT cover, rather than implying silent
   completeness -- see the module-level "NOT COVERED" section below.

Harness note: the harness NEVER wraps test bodies in `set -euo pipefail`.
Phase 1's own dynamic smoke test recorded this exact trap (EVALUATION.md /
PROPOSAL.md Sec.7): the first perturbation attempt used `set -euo pipefail`
and the harness aborted on its FIRST assertion, rc=1, with ZERO assertions
actually reported -- "a red suite is not the same as the right assertion
firing, and a probe that cannot tell them apart proves nothing." This
suite's harness leaves shell options up to each test body so a function
returning non-zero (which almost every guard here does, by design) never
silently truncates the test.

NOT COVERED (cannot be exercised from a container -- MANUAL CHECKLIST).
The shipped library is kept BYTE-IDENTICAL to Phase 1's independently
verified extraction (see the `TestShippedLibraryIntegrity` class below), so
this checklist is carried here rather than added into the library's own
header:

    1. Key not in the agent:  ssh-add -D; ./<plan>/deploy.bash --check
       EXPECT one clean passphrase prompt BEFORE any tee'd output.
    2. Key already loaded:    ssh-add <key>; re-run
       EXPECT "already loaded" and NO second prompt.
    3. Change gate on a REAL terminal: ./<plan>/deploy.bash
       EXPECT the prompt AFTER the banner (ordered), a wrong answer to
       abort before the first mutating leg, and -y to skip.
    4. Ctrl-C mid-run: the run log still contains every line up to the
       interrupt (drain-then-scrub ordering, PROPOSAL.md Sec.3.6).

Also not covered: the tee/fifo run-log drain under REAL signal delivery
(INT/TERM/HUP) to a live `plan_start_log` session, and live TTY
colour-forcing (`PLANLIB_FORCE_COLOR_VAR`). Phase 1's evaluation did a
one-off manual perturbation of the HUP trap line and confirmed exactly one
assertion failed, naming HUP (EVALUATION.md Sec.1.3); that specific
signal-timing perturbation is not repeated here as an automated CI check,
because reliably synthesising signal delivery against a backgrounded
`tee | awk` pipeline is inherently flake-prone in a containerised runner
and the payoff (re-proving a already-recorded, one-shot finding) does not
justify that flakiness risk. What IS covered below instead is the no-TTY
path through `_plan_tty_openable` / `plan_confirm` (achievable
deterministically via `setsid`), and the pure/structural guards that do
not depend on real signal timing.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.plan_workflow import planlib_template_path

_LIBRARY_PATH = planlib_template_path()

# The set of env var PREFIXES the library reads/exports. Stripped from every
# subprocess's environment before a test-specific override is applied, so
# state from the pytest process's own environment (or a leaked prior test,
# were subprocess isolation ever weakened) can never contaminate a result.
_PLANLIB_ENV_PREFIXES = ("PLANLIB_", "PLAN_")


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_PLANLIB_ENV_PREFIXES)}
    if extra:
        env.update(extra)
    return env


def _write_harness(tmp_path: Path, body: str) -> Path:
    """Write a bash script that sources the library then runs `body`."""
    script = tmp_path / "harness.bash"
    script.write_text(f'#!/usr/bin/env bash\nsource "{_LIBRARY_PATH}"\n{body}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _run_bash(
    tmp_path: Path,
    body: str,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
    setsid: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Source the library, run `body`, and return the completed process."""
    script = _write_harness(tmp_path, body)
    argv = ["setsid", "bash", str(script)] if setsid else ["bash", str(script)]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env=_clean_env(env),
        input=stdin_text,
        stdin=subprocess.DEVNULL if stdin_text is None and setsid else None,
    )


class TestShippedLibraryIntegrity:
    """Pins the file this whole suite exercises to Phase 1's verified extraction."""

    def test_bundled_library_is_syntactically_clean(self) -> None:
        """`bash -n` exit code alone is NOT trusted (PROPOSAL.md's own stated
        caveat): a malformed conditional prints a diagnostic to stderr and
        STILL exits 0, so stderr must be asserted empty too.
        """
        result = subprocess.run(
            ["bash", "-n", str(_LIBRARY_PATH)],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_DEFAULT,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""


class TestDoubleSourcingGuard:
    def test_sourcing_twice_is_a_clean_noop(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, f'source "{_LIBRARY_PATH}"\necho "OK=$PLANLIB_VERSION"')
        assert result.returncode == 0
        assert result.stdout.count("OK=1.0.0") == 1


class TestPlanStripCr:
    """`_plan_strip_cr` — pure predicate, only a TRAILING CR is stripped."""

    def test_strips_a_trailing_cr(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "printf '%s' \"$(_plan_strip_cr $'hello\\r')\"")
        assert result.stdout == "hello"

    def test_no_cr_is_unchanged(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "printf '%s' \"$(_plan_strip_cr 'hello')\"")
        assert result.stdout == "hello"

    def test_only_trailing_cr_is_stripped_not_an_internal_one(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "_plan_strip_cr $'hel\\rlo' | cat -A")
        # cat -A renders an embedded CR as ^M so it survives assertion visibly.
        assert "hel^Mlo" in result.stdout


class TestPlanFingerprintPresent:
    """`_plan_fingerprint_present` — the space-delimited exact-match predicate.

    The correctness property under test is explicitly named in the
    library's own comment: a prefix like SHA256:AA must NOT match a listing
    that only contains SHA256:AAA.
    """

    def test_exact_match_succeeds(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path, '_plan_fingerprint_present "SHA256:AAA" "SHA256:AAA SHA256:BBB"'
        )
        assert result.returncode == 0

    def test_prefix_collision_is_correctly_rejected(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, '_plan_fingerprint_present "SHA256:AA" "SHA256:AAA"')
        assert result.returncode == 1

    def test_absent_fingerprint_is_rejected(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path, '_plan_fingerprint_present "SHA256:ZZZ" "SHA256:AAA SHA256:BBB"'
        )
        assert result.returncode == 1


class TestPlanFindRepoRoot:
    """`_plan_find_repo_root` — script-relative, filesystem-only, boundary-bounded.

    `test_refuses_to_walk_past_nested_repo_boundary` reproduces the specific
    incident class PROPOSAL.md Sec.1.1 describes: an inner checkout must
    never silently resolve to an OUTER repo's marker.
    """

    def test_finds_marker_several_directories_below(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        deep = repo / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (repo / "marker.txt").write_text("root\n")
        result = _run_bash(
            tmp_path,
            f'PLANLIB_ROOT_MARKER=marker.txt\n_plan_find_repo_root "{deep}"',
        )
        assert result.returncode == 0
        assert result.stdout == str(repo)

    def test_refuses_to_walk_past_nested_repo_boundary(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        (outer / ".git").mkdir(parents=True)
        (outer / "marker.txt").write_text("outer root\n")
        inner_src = outer / "vendor" / "inner-repo" / "src"
        inner_src.mkdir(parents=True)
        (inner_src.parent / ".git").mkdir()  # inner-repo has its OWN boundary
        # Deliberately no marker.txt anywhere inside inner-repo.
        result = _run_bash(
            tmp_path,
            f'PLANLIB_ROOT_MARKER=marker.txt\n_plan_find_repo_root "{inner_src}"',
        )
        assert result.returncode == 1
        assert result.stdout == ""

    def test_marker_is_tested_before_boundary_when_the_root_holds_both(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "marker.txt").write_text("root\n")
        result = _run_bash(
            tmp_path, f'PLANLIB_ROOT_MARKER=marker.txt\n_plan_find_repo_root "{repo}"'
        )
        assert result.returncode == 0
        assert result.stdout == str(repo)

    def test_no_marker_anywhere_refuses(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        result = _run_bash(
            tmp_path, f'PLANLIB_ROOT_MARKER=marker.txt\n_plan_find_repo_root "{repo}"'
        )
        assert result.returncode == 1


class TestPlanInitResolvesFromScriptLocationNotCwd:
    """`plan_init` — the primitive PROPOSAL.md Sec.1.1's incident is about.

    `test_resolves_root_from_script_location_regardless_of_cwd` is the load-
    bearing regression test: it runs the calling script BY PATH from a
    directory belonging to a COMPLETELY DIFFERENT repo (one with its own,
    different, root marker) and asserts PLAN_REPO_ROOT still resolves to
    the CALLING SCRIPT's own repo -- proving script-relative resolution
    beats `git rev-parse --show-toplevel`'s cwd-relative answer.
    """

    def test_requires_root_marker_to_be_set_first(self, tmp_path: Path) -> None:
        caller = tmp_path / "caller.bash"
        caller.write_text(
            f'#!/usr/bin/env bash\nsource "{_LIBRARY_PATH}"\nplan_init "${{BASH_SOURCE[0]}}"\n'
        )
        result = subprocess.run(
            ["bash", str(caller)],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_DEFAULT,
            env=_clean_env(),
        )
        assert result.returncode == 1
        assert "PLANLIB_ROOT_MARKER is unset" in result.stderr

    def test_refuses_loudly_when_no_marker_between_script_and_boundary(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        scripts_dir = repo / "CLAUDE" / "Plan" / "00001-example"
        scripts_dir.mkdir(parents=True)
        caller = scripts_dir / "verify.bash"
        caller.write_text(
            f"#!/usr/bin/env bash\n"
            f"PLANLIB_ROOT_MARKER=nonexistent-marker.txt\n"
            f'source "{_LIBRARY_PATH}"\n'
            f'plan_init "${{BASH_SOURCE[0]}}"\n'
        )
        result = subprocess.run(
            ["bash", str(caller)],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_DEFAULT,
            env=_clean_env(),
        )
        assert result.returncode == 1
        assert "repo boundary ON PURPOSE" in result.stderr

    def test_resolves_root_from_script_location_regardless_of_cwd(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        scripts_dir = repo / "CLAUDE" / "Plan" / "00001-example"
        scripts_dir.mkdir(parents=True)
        (repo / "marker.txt").write_text("root\n")
        caller = scripts_dir / "verify.bash"
        caller.write_text(
            f"#!/usr/bin/env bash\n"
            f"PLANLIB_ROOT_MARKER=marker.txt\n"
            f'source "{_LIBRARY_PATH}"\n'
            f'plan_init "${{BASH_SOURCE[0]}}"\n'
            f'printf "%s" "$PLAN_REPO_ROOT"\n'
        )

        # A DIFFERENT repo, with its OWN, DIFFERENT root marker -- the
        # operator ran the script BY PATH from here.
        elsewhere = tmp_path / "totally-unrelated-checkout"
        elsewhere.mkdir()
        (elsewhere / "marker.txt").write_text("a different repo's marker\n")

        result = subprocess.run(
            ["bash", str(caller)],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_DEFAULT,
            env=_clean_env(),
            cwd=elsewhere,
        )
        assert result.returncode == 0
        assert result.stdout == str(repo)


class TestPlanMode:
    def test_deploy_is_accepted(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode deploy\necho "MODE=$PLAN_MODE"')
        assert result.returncode == 0
        assert "MODE=deploy" in result.stdout

    def test_gather_is_accepted(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode gather\necho "MODE=$PLAN_MODE"')
        assert result.returncode == 0
        assert "MODE=gather" in result.stdout

    def test_invalid_mode_is_refused_and_names_the_bad_value(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "plan_mode sideways")
        assert result.returncode == 1
        assert "sideways" in result.stderr


class TestChangeGate:
    """`plan_gate_change` / `_plan_assert_change_allowed` — gate on STATE
    CHANGE, never on target name (PROPOSAL.md Sec.3.9). Each pair below is a
    positive/negative control: the guard must fire on the wrong mode and
    stay silent on the right one.
    """

    def test_gather_mode_refuses_the_gate(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode gather\nplan_gate_change "test"')
        assert result.returncode == 1
        assert "nothing to gate" in result.stderr

    def test_gate_requires_deploy_mode_declared_first(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_gate_change "test"')  # PLAN_MODE unset
        assert result.returncode == 1
        assert "plan_mode deploy" in result.stderr

    def test_check_flag_auto_passes_the_gate(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            'plan_mode deploy\nPLAN_CHECK=1\nplan_gate_change "a live change"\necho "GATE=$PLAN_GATE_PASSED"',
        )
        assert result.returncode == 0
        assert "GATE=1" in result.stdout
        assert "auto-passed" in result.stdout

    def test_assert_change_allowed_refuses_a_command_before_the_gate(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "plan_mode deploy\nplan_run true")
        assert result.returncode == 1
        assert "plan_gate_change" in result.stderr

    def test_assert_change_allowed_passes_through_in_gather_mode(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode gather\nplan_run true\necho "RC=$?"')
        assert result.returncode == 0
        assert "RC=0" in result.stdout


class TestPlanDeployLegSubshellGuard:
    """`BASH_SUBSHELL` misuse guard (PROPOSAL.md Sec.3.11) — the subtlest
    thing in the library: `exit` inside `$( )` ends only the subshell, so a
    failed leg would print [ABORT] and the run would continue to the next
    statement, looking aborted while actually continuing. The guard takes
    the WHOLE process down with `kill -TERM "$$"` instead.
    """

    def test_bare_top_level_call_succeeds(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode deploy\nplan_deploy_leg "ok" true\necho "done"')
        assert result.returncode == 0
        assert "done" in result.stdout

    def test_inside_command_substitution_kills_the_whole_run(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            "plan_mode deploy\n" 'out="$(plan_deploy_leg "bad" true)"\n' 'echo "unreachable"\n',
        )
        assert result.returncode != 0
        assert "unreachable" not in result.stdout
        assert "BASH_SUBSHELL" in result.stderr

    def test_used_in_gather_mode_is_refused(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode gather\nplan_deploy_leg "x" true')
        assert result.returncode == 1
        assert "plan_mode deploy" in result.stderr


class TestPlanGatherLeg:
    def test_records_a_failed_leg_and_continues(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            "plan_mode gather\n"
            'plan_gather_leg "one" false\n'
            'plan_gather_leg "two" true\n'
            'echo "FAILED=$PLAN_FAILED_LEGS"\n'
            'echo "reached-end"\n',
        )
        assert result.returncode == 0
        assert "FAILED=one" in result.stdout
        assert "reached-end" in result.stdout

    def test_used_in_deploy_mode_is_refused(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_mode deploy\nplan_gather_leg "x" true')
        assert result.returncode == 1
        assert "plan_mode gather" in result.stderr


class TestPlanFinishExitAgreesWithText:
    """`plan_finish` (PROPOSAL.md Sec.3.12): the exit status must AGREE with
    the printed text. A run reporting failed legs that still exits 0 is
    exactly Sec.1.1's founding failure class -- a control that reports
    success without having done its job.
    """

    def test_no_failed_legs_exits_zero_and_says_ok(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "plan_finish")
        assert result.returncode == 0
        assert "all legs OK" in result.stdout

    def test_failed_legs_exit_nonzero_and_name_them(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'PLAN_FAILED_LEGS="alpha beta"\nplan_finish')
        assert result.returncode == 1
        assert "FAILED legs: alpha beta" in result.stderr


class TestPlanLoadSshKeysOrdering:
    """The ordering enforcement (PROPOSAL.md Sec.3.5) is a RUNTIME ERROR, not
    a comment: calling `plan_load_ssh_keys` after `plan_start_log` must be
    refused, because a passphrase prompt issued after the tee redirect is
    flooded and garbled. Only the ordering CHECK is exercised here -- actual
    ssh-agent interaction is TTY/agent-dependent and out of scope for this
    suite (see the module docstring's NOT COVERED section).
    """

    def test_refuses_when_log_already_started(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "PLAN_LOG_STARTED=1\nplan_load_ssh_keys /nonexistent/key")
        assert result.returncode == 1
        assert "must be called BEFORE plan_start_log" in result.stderr


class TestPlanTtyOpenable:
    """`_plan_tty_openable` — existence of /dev/tty is not enough; the probe
    must actually OPEN it. `setsid` deterministically detaches the process
    from any controlling terminal, reproducing the no-TTY path this suite
    CAN cover (per the module docstring's NOT COVERED section, the live
    interactive TTY path cannot be).
    """

    def test_no_controlling_terminal_is_detected(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            "if _plan_tty_openable; then\n"
            '    echo "openable"\n'
            "else\n"
            '    echo "not-openable"\n'
            "fi\n",
            setsid=True,
        )
        assert result.returncode == 0
        assert "not-openable" in result.stdout

    def test_plan_confirm_refuses_without_a_controlling_terminal(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_confirm "would you like to proceed"', setsid=True)
        assert result.returncode == 1
        assert "no controlling terminal" in result.stderr

    def test_plan_confirm_auto_confirms_via_assume_yes_even_without_a_tty(
        self, tmp_path: Path
    ) -> None:
        """-y/--yes bypasses the TTY requirement entirely -- the documented
        non-interactive escape hatch.
        """
        result = _run_bash(
            tmp_path,
            'PLAN_ASSUME_YES=1\nplan_confirm "would you like to proceed"',
            setsid=True,
        )
        assert result.returncode == 0
        assert "auto-confirmed" in result.stdout


class TestPlanParseCommonFlags:
    def test_check_flag_sets_check_state_and_check_args(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            "plan_parse_common_flags --check foo bar\n"
            'echo "CHECK=$PLAN_CHECK"\n'
            'echo "ARGS=${PLAN_CHECK_ARGS[*]}"\n'
            'echo "REMAINING=${PLAN_REMAINING_ARGS[*]}"\n',
        )
        assert result.returncode == 0
        assert "CHECK=1" in result.stdout
        assert "ARGS=--check" in result.stdout
        assert "REMAINING=foo bar" in result.stdout

    def test_yes_flag_sets_assume_yes(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, 'plan_parse_common_flags -y\necho "YES=$PLAN_ASSUME_YES"')
        assert result.returncode == 0
        assert "YES=1" in result.stdout

    def test_help_flag_prints_usage_and_exits_zero_without_reaching_further_code(
        self, tmp_path: Path
    ) -> None:
        result = _run_bash(
            tmp_path,
            'PLAN_USAGE="usage: custom help text"\n'
            "plan_parse_common_flags --help\n"
            'echo "unreachable"\n',
        )
        assert result.returncode == 0
        assert "usage: custom help text" in result.stdout
        assert "unreachable" not in result.stdout

    def test_unknown_positional_args_pass_through(self, tmp_path: Path) -> None:
        result = _run_bash(
            tmp_path,
            "plan_parse_common_flags positional1 --check positional2\n"
            'echo "REMAINING=${PLAN_REMAINING_ARGS[*]}"\n',
        )
        assert result.returncode == 0
        assert "REMAINING=positional1 positional2" in result.stdout


class TestPlanErr:
    """`_plan_err` — loud failure, never calls `exit`, errexit-safe via the
    `|| return 1` convention (PROPOSAL.md Sec.3.2).
    """

    def test_prints_to_stderr_with_fatal_prefix_and_returns_1(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, '_plan_err "boom"\necho "rc=$?"')
        assert "[FATAL] boom" in result.stderr
        assert "boom" not in result.stdout
        assert "rc=1" in result.stdout

    def test_or_return_convention_is_errexit_safe(self, tmp_path: Path) -> None:
        """Under `set -e`, `_plan_err "..." || return 1` lets the calling
        function return cleanly (skipping the line after it) instead of the
        whole script aborting mid-function on the bare `_plan_err` call.
        """
        result = _run_bash(
            tmp_path,
            "set -e\n"
            "f() {\n"
            '    _plan_err "reason" || return 1\n'
            '    echo "must not print"\n'
            "}\n"
            'if f; then echo "f-succeeded"; else echo "f-failed rc=$?"; fi\n',
        )
        assert result.returncode == 0
        assert "must not print" not in result.stdout
        assert "f-failed" in result.stdout


class TestPlanRun:
    """`plan_run` — delegates when configured, runs directly otherwise;
    stdin is always closed for the delegated/direct command.
    """

    def test_no_delegate_runs_the_command_directly(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "plan_mode gather\nplan_run echo hello-direct")
        assert result.returncode == 0
        assert "hello-direct" in result.stdout

    def test_delegate_is_prefixed_when_configured(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        delegate = repo / "runner.bash"
        delegate.write_text('#!/usr/bin/env bash\necho "delegate got: $*"\n')
        delegate.chmod(delegate.stat().st_mode | stat.S_IXUSR)
        result = _run_bash(
            tmp_path,
            f'PLAN_REPO_ROOT="{repo}"\n'
            f'PLANLIB_DELEGATE="runner.bash"\n'
            f"plan_mode gather\n"
            f"plan_run mycommand --flag\n",
        )
        assert result.returncode == 0
        assert "delegate got: mycommand --flag" in result.stdout

    def test_stdin_is_closed_for_the_delegated_command(self, tmp_path: Path) -> None:
        """A delegated command must not drain the calling script's own
        stdin out from under a LATER prompt (PROPOSAL.md Sec.3.10).
        """
        result = _run_bash(
            tmp_path,
            "plan_mode gather\nplan_run cat",
            stdin_text="should never be read\n",
        )
        assert result.returncode == 0
        assert result.stdout == ""


class TestPlanListReports:
    def test_lists_files_matching_report_glob(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "deploy-report.txt").write_text("x\n")
        (run_dir / "unrelated.log").write_text("y\n")
        result = _run_bash(tmp_path, f'PLAN_RUN_DIR="{run_dir}"\nplan_list_reports')
        assert result.returncode == 0
        assert "deploy-report.txt" in result.stdout
        assert "unrelated.log" not in result.stdout

    def test_silent_when_no_run_dir(self, tmp_path: Path) -> None:
        result = _run_bash(tmp_path, "plan_list_reports")
        assert result.returncode == 0
        assert result.stdout == ""


@pytest.mark.parametrize("mode", ["deploy", "gather"])
def test_plan_mode_export_is_visible_to_a_child_process(tmp_path: Path, mode: str) -> None:
    """PLAN_MODE is exported (Sec.3.4) so a delegated child process can read
    the run's own declared nature.
    """
    result = _run_bash(
        tmp_path,
        f"plan_mode {mode}\nbash -c 'echo \"CHILD_SAW=$PLAN_MODE\"'",
    )
    assert result.returncode == 0
    assert f"CHILD_SAW={mode}" in result.stdout
