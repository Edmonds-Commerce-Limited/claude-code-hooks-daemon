"""Tests for utils/process_probe.py — self-matching process probe classification.

Plan 00363, Task 1.1/1.2. The corpus is anchored on the real incident:

    until ! pgrep -f "run_02" >/dev/null; do sleep 30; done

The Bash tool runs every command through ``bash -c "<command>"``, so the
pattern being searched for sits in the waiting shell's OWN argv. ``pgrep -f``
therefore always finds at least one match — itself — and the loop never exits.

The classifier answers three questions per probe: does its pattern match its
own command line, would acting on the match kill the caller, and does it sit
inside a construct that waits.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.process_probe import (
    ProbeKind,
    ProbeVerdict,
    ProcessProbe,
    WaitConstruct,
    WrapperPidWait,
    bracket_trick,
    classify_liveness_loops,
    classify_process_probes,
    classify_wrapper_pid_waits,
)

# The verbatim incident command from the field report.
_INCIDENT = 'until ! pgrep -f "run_02" >/dev/null; do sleep 30; done'


def _only(command: str) -> ProcessProbe:
    """The single probe ``command`` contains, failing loudly if it is not one."""
    probes = classify_process_probes(command)
    assert len(probes) == 1, f"expected exactly one probe in {command!r}, got {probes!r}"
    return probes[0]


class TestNoProbe:
    """Commands carrying no process probe at all produce nothing."""

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "   ",
            "ls -la",
            "git status",
            "grep -n needle file.txt",
            # `ps` with no grep stage is a plain listing, not a probe for a
            # named process.
            "ps aux",
        ],
    )
    def test_no_probes_detected(self, command: str) -> None:
        assert classify_process_probes(command) == ()

    def test_prose_naming_the_incident_is_not_a_probe(self) -> None:
        """An echoed sentence is text; nothing in it executes."""
        assert classify_process_probes(f'echo "{_INCIDENT}"') == ()

    def test_quoted_heredoc_body_is_not_a_probe(self) -> None:
        """A quoted-delimiter heredoc body is data — bash never parses it."""
        command = f"cat > notes.md <<'EOF'\n{_INCIDENT}\nEOF"
        assert classify_process_probes(command) == ()


class TestIncidentShape:
    """The motivating command, classified end to end."""

    @pytest.fixture
    def probe(self) -> ProcessProbe:
        return _only(_INCIDENT)

    def test_kind_is_pgrep(self, probe: ProcessProbe) -> None:
        assert probe.kind is ProbeKind.PGREP

    def test_pattern_is_the_literal(self, probe: ProcessProbe) -> None:
        assert probe.pattern == "run_02"

    def test_verdict_is_self_matching(self, probe: ProcessProbe) -> None:
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.is_self_matching is True

    def test_sits_inside_a_loop(self, probe: ProcessProbe) -> None:
        assert probe.wait_construct is WaitConstruct.LOOP

    def test_is_not_lethal(self, probe: ProcessProbe) -> None:
        """`pgrep` reports; it does not signal. Only `pkill` kills the caller."""
        assert probe.lethal is False

    def test_safe_rewrite_is_the_bracket_trick(self, probe: ProcessProbe) -> None:
        assert probe.safe_rewrite == 'pgrep -f "[r]un_02"'


class TestPgrepFullMatch:
    """`pgrep -f` reads the full command line, which is where the shell lives."""

    @pytest.mark.parametrize(
        "command",
        [
            "pgrep -f run_02",
            'pgrep -f "run_02"',
            "pgrep --full run_02",
            # A short-flag cluster carries -f exactly as a lone flag does.
            "pgrep -lf run_02",
            # An option that takes a value must not be mistaken for the pattern.
            "pgrep -u root -f run_02",
            # A redirect is not an operand.
            "pgrep -f run_02 > /dev/null",
            "pgrep -f run_02 >/dev/null 2>&1",
        ],
    )
    def test_literal_pattern_is_self_matching(self, command: str) -> None:
        probe = _only(command)
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.pattern == "run_02"

    @pytest.mark.parametrize(
        "command",
        [
            "/usr/bin/pgrep -f run_02",
            '"pgrep" -f run_02',
            # A backslash suppresses alias expansion; bash still runs pgrep.
            "\\pgrep -f run_02",
            "env pgrep -f run_02",
            "PATTERN=x pgrep -f run_02",
            "pgrep \\\n  -f run_02",
        ],
    )
    def test_respelling_the_command_name_does_not_hide_it(self, command: str) -> None:
        assert _only(command).verdict is ProbeVerdict.SELF_MATCHING

    def test_one_shot_probe_has_no_wait_construct(self) -> None:
        assert _only("pgrep -f run_02").wait_construct is None

    def test_gated_probe_is_still_one_shot(self) -> None:
        """`&&` runs the next command once; it does not wait."""
        assert _only("pgrep -f run_02 && echo found").wait_construct is None

    def test_classic_self_reference_has_no_external_match(self) -> None:
        """The probe's own text explains the match; nothing else needs naming."""
        assert _only("pgrep -f run_02").external_match is None


class TestExternalCollateralMatch:
    """A bracket-tricked probe can still self-match through OTHER text.

    Confirmed against real `pgrep`: a simple command that is NOT the tail of
    the script — anything with a real `|| …`/`&& …` after it that the shell
    must be ready to run — is never exec-optimised away, so its cmdline stays
    the FULL script text for the life of the shell. A companion
    `|| echo "no <name>"` fallback that spells the target unescaped therefore
    keeps the probe self-matching even after its own pattern is bracketed —
    a real hazard, not a false positive, so the verdict must stay
    SELF_MATCHING. `external_match` names what the bracket trick on the
    probe's own text cannot fix.
    """

    def test_the_offending_text_can_be_the_probes_own_fallback(self) -> None:
        """The reported bug's exact shape: the fallback belongs to THIS probe."""
        command = 'pgrep -f "[p]ytest" || echo "no pytest"'
        probe = _only(command)
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.external_match == "pytest"

    def test_bracket_tricked_probe_with_no_collateral_text_is_safe(self) -> None:
        """The ordinary case the bracket trick is meant for: no residual match."""
        probe = _only('pgrep -f "[p]ytest" || echo "no match"')
        assert probe.verdict is ProbeVerdict.SAFE
        assert probe.external_match is None

    def test_safe_rewrite_offers_nothing_once_already_bracketed(self) -> None:
        """`safe_rewrite` cannot help here; the message must lean on `external_match`."""
        probe = _only('pgrep -f "[p]ytest" || echo "no pytest"')
        assert probe.safe_rewrite is None
        assert probe.external_match == "pytest"

    def test_an_unbracketed_probe_reports_no_external_match(self) -> None:
        """Fix the probe's own spelling first; external_match waits for a retry."""
        probe = _only('pgrep -f "pytest" || echo "no pytest"')
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.external_match is None
        assert probe.safe_rewrite == 'pgrep -f "[p]ytest"'


class TestPgrepSafeForms:
    """Forms that cannot match the probing shell's own command line."""

    @pytest.mark.parametrize(
        "command",
        [
            # Name mode compares against `comm`, which for the waiting shell is
            # `bash` — never the pattern.
            "pgrep run_02",
            "pgrep -l run_02",
            # -x demands the WHOLE command line equal the pattern.
            "pgrep -x run_02",
            "pgrep -xf run_02",
            "pgrep --exact --full run_02",
            # The bracket trick: the pattern's own text no longer matches it.
            'pgrep -f "[r]un_02"',
            "pgrep -f '[r]un_02'",
            # A regex that genuinely cannot match its own spelling.
            'pgrep -f "run_0[3-9]"',
            # Nothing to match with.
            "pgrep -f",
        ],
    )
    def test_verdict_is_safe(self, command: str) -> None:
        assert _only(command).verdict is ProbeVerdict.SAFE

    def test_safe_probe_offers_no_rewrite(self) -> None:
        assert _only('pgrep -f "[r]un_02"').safe_rewrite is None

    def test_bracket_trick_inside_a_loop_is_still_safe(self) -> None:
        probe = _only('until ! pgrep -f "[r]un_02" >/dev/null; do sleep 30; done')
        assert probe.verdict is ProbeVerdict.SAFE
        assert probe.wait_construct is WaitConstruct.LOOP


class TestUnresolvedPatterns:
    """A pattern built by expansion cannot be judged, so it is never denied."""

    @pytest.mark.parametrize(
        "command",
        [
            'pgrep -f "$PATTERN"',
            "pgrep -f ${PATTERN}",
            'pgrep -f "$(cat pattern.txt)"',
            'pkill -f "$JOB"',
        ],
    )
    def test_verdict_is_unresolved(self, command: str) -> None:
        probe = _only(command)
        assert probe.verdict is ProbeVerdict.UNRESOLVED
        assert probe.is_self_matching is False

    def test_single_quotes_expand_nothing_so_the_pattern_is_literal(self) -> None:
        """`'$PATTERN'` searches for the eight characters `$PATTERN`."""
        probe = _only("pgrep -f '$PATTERN'")
        assert probe.verdict is ProbeVerdict.SELF_MATCHING

    def test_unresolved_probe_offers_no_rewrite(self) -> None:
        assert _only('pgrep -f "$PATTERN"').safe_rewrite is None


class TestPkill:
    """`pkill -f` does not report the self-match — it signals it."""

    def test_literal_pkill_is_lethal(self) -> None:
        probe = _only("pkill -f run_02")
        assert probe.kind is ProbeKind.PKILL
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.lethal is True

    def test_safe_rewrite_names_pkill(self) -> None:
        assert _only("pkill -f run_02").safe_rewrite == 'pkill -f "[r]un_02"'

    @pytest.mark.parametrize(
        "command",
        ["pkill run_02", "pkill -x run_02", 'pkill -f "[r]un_02"'],
    )
    def test_safe_pkill_is_not_lethal(self, command: str) -> None:
        probe = _only(command)
        assert probe.verdict is ProbeVerdict.SAFE
        assert probe.lethal is False

    def test_signal_option_value_is_not_the_pattern(self) -> None:
        assert _only("pkill --signal TERM -f run_02").pattern == "run_02"


class TestPgrepPipedToAKiller:
    """`pgrep -f … | xargs kill` reaches the same end as `pkill -f`."""

    @pytest.mark.parametrize(
        "command",
        [
            "pgrep -f run_02 | xargs kill",
            "pgrep -f run_02 | xargs -r kill -9",
            "pgrep -f run_02 | xargs -I{} kill -TERM {}",
        ],
    )
    def test_is_lethal(self, command: str) -> None:
        probes = classify_process_probes(command)
        pgrep_probes = [probe for probe in probes if probe.kind is ProbeKind.PGREP]
        assert len(pgrep_probes) == 1
        assert pgrep_probes[0].lethal is True

    def test_piped_to_wc_is_not_lethal(self) -> None:
        probes = classify_process_probes("pgrep -f run_02 | wc -l")
        assert [probe.lethal for probe in probes if probe.kind is ProbeKind.PGREP] == [False]

    def test_a_safe_pattern_piped_to_kill_is_not_lethal(self) -> None:
        """Lethality needs a SELF-match; killing other processes is the job."""
        probes = classify_process_probes('pgrep -f "[r]un_02" | xargs kill')
        assert [probe.lethal for probe in probes if probe.kind is ProbeKind.PGREP] == [False]

    def test_signalling_is_recorded_apart_from_the_verdict(self) -> None:
        """A caller warning about an unresolvable pattern needs this separately."""
        probe = _only('pgrep -f "$JOB" | xargs kill')
        assert probe.signals is True
        assert probe.verdict is ProbeVerdict.UNRESOLVED
        assert probe.lethal is False

    def test_a_reporting_probe_does_not_signal(self) -> None:
        assert _only("pgrep -f run_02").signals is False


class TestPsPipedToGrep:
    """`ps … | grep <pattern>` matches the grep's own line in ps output."""

    def test_bare_ps_grep_is_self_matching(self) -> None:
        probe = _only("ps aux | grep run_02")
        assert probe.kind is ProbeKind.PS_GREP
        assert probe.pattern == "run_02"
        assert probe.verdict is ProbeVerdict.SELF_MATCHING

    def test_safe_rewrite_uses_the_bracket_trick(self) -> None:
        assert _only("ps aux | grep run_02").safe_rewrite == 'ps aux | grep "[r]un_02"'

    @pytest.mark.parametrize(
        "command",
        [
            "ps aux | grep run_02 | grep -v grep",
            "ps aux | grep -v grep | grep run_02",
            'ps aux | grep run_02 | grep -v "grep"',
            "ps -ef | grep run_02 | grep -v $$",
            'ps -ef | grep run_02 | grep -v "$$"',
            'ps aux | grep "[r]un_02"',
            "ps aux | grep --invert-match grep | grep run_02",
        ],
    )
    def test_self_excluded_forms_are_safe(self, command: str) -> None:
        probes = classify_process_probes(command)
        ps_probes = [probe for probe in probes if probe.kind is ProbeKind.PS_GREP]
        assert len(ps_probes) == 1
        assert ps_probes[0].verdict is ProbeVerdict.SAFE

    def test_ps_grep_inside_a_loop_reports_the_loop(self) -> None:
        command = "while ps aux | grep run_02; do sleep 5; done"
        probe = _only(command)
        assert probe.wait_construct is WaitConstruct.LOOP

    def test_ps_grep_is_never_lethal(self) -> None:
        assert _only("ps aux | grep run_02").lethal is False


class TestPidBasedProbes:
    """A probe naming a PID cannot match the probing shell."""

    @pytest.mark.parametrize(
        ("command", "kind"),
        [
            ("ps -p 1234", ProbeKind.PS_PID),
            ("ps -o pid= -p 1234", ProbeKind.PS_PID),
            ('ps -p "$PID"', ProbeKind.PS_PID),
            ("ps --pid 1234", ProbeKind.PS_PID),
            ("kill -0 1234", ProbeKind.KILL_PID),
            ('kill -0 "$PID"', ProbeKind.KILL_PID),
        ],
    )
    def test_pid_probe_is_safe(self, command: str, kind: ProbeKind) -> None:
        probe = _only(command)
        assert probe.kind is kind
        assert probe.verdict is ProbeVerdict.SAFE
        assert probe.lethal is False

    def test_pid_wait_loop_is_safe(self) -> None:
        probe = _only('while kill -0 "$PID" 2>/dev/null; do sleep 1; done')
        assert probe.verdict is ProbeVerdict.SAFE
        assert probe.wait_construct is WaitConstruct.LOOP

    def test_a_real_kill_is_not_a_probe(self) -> None:
        """Only `kill -0` probes; `kill -9` acts, and is another rule's business."""
        assert classify_process_probes("kill -9 1234") == ()


class TestWaitConstructs:
    """Where a probe sits decides whether a wrong answer becomes a hang."""

    @pytest.mark.parametrize(
        "command",
        [
            'until ! pgrep -f "run_02" >/dev/null; do sleep 30; done',
            "while pgrep -f run_02; do sleep 5; done",
            "while pgrep -f run_02 > /dev/null; do sleep 5; done",
            "for i in 1 2 3; do pgrep -f run_02; sleep 5; done",
            "set -euo pipefail\nuntil ! pgrep -f run_02; do sleep 30; done",
        ],
    )
    def test_loop_is_detected(self, command: str) -> None:
        assert _only(command).wait_construct is WaitConstruct.LOOP

    @pytest.mark.parametrize(
        "command",
        [
            "watch pgrep -f run_02",
            "watch -n 5 pgrep -f run_02",
            "watch -n 5 'pgrep -f run_02'",
        ],
    )
    def test_watch_is_detected(self, command: str) -> None:
        assert _only(command).wait_construct is WaitConstruct.WATCH

    def test_timeout_wrapping_a_shell_is_detected(self) -> None:
        probe = _only("timeout 600 bash -c 'pgrep -f run_02'")
        assert probe.wait_construct is WaitConstruct.TIMEOUT
        assert probe.verdict is ProbeVerdict.SELF_MATCHING

    def test_a_loop_inside_a_timeout_reports_the_loop(self) -> None:
        """The inner construct is the more specific truth, so it wins."""
        command = "timeout 600 bash -c 'until ! pgrep -f run_02; do sleep 5; done'"
        assert _only(command).wait_construct is WaitConstruct.LOOP

    def test_bash_c_without_a_wrapper_still_finds_the_probe(self) -> None:
        probe = _only("bash -c 'pgrep -f run_02'")
        assert probe.verdict is ProbeVerdict.SELF_MATCHING
        assert probe.wait_construct is None

    def test_a_probe_after_a_loop_is_not_inside_it(self) -> None:
        command = "for i in 1 2; do sleep 1; done; pgrep -f run_02"
        assert _only(command).wait_construct is None

    def test_an_unterminated_loop_still_reports_a_loop(self) -> None:
        """A missing `done` is a syntax error; reporting the loop is the safe read."""
        assert _only("while pgrep -f run_02; do sleep 1").wait_construct is WaitConstruct.LOOP


class TestMultipleProbes:
    """Every probe in a command is classified, not just the first."""

    def test_two_probes_are_both_reported(self) -> None:
        probes = classify_process_probes("pgrep -f run_01; pkill -f run_02")
        assert [probe.kind for probe in probes] == [ProbeKind.PGREP, ProbeKind.PKILL]
        assert [probe.pattern for probe in probes] == ["run_01", "run_02"]

    def test_a_safe_probe_does_not_launder_an_unsafe_one(self) -> None:
        probes = classify_process_probes('pgrep -f "[r]un_01"; pgrep -f run_02')
        assert [probe.verdict for probe in probes] == [
            ProbeVerdict.SAFE,
            ProbeVerdict.SELF_MATCHING,
        ]


class TestPatternIsReadAsARegex:
    """`pgrep -f` matches an ERE against the full command line, so we do too."""

    def test_a_pattern_that_cannot_match_its_own_spelling_is_safe(self) -> None:
        assert _only('pgrep -f "run_0[3-9]"').verdict is ProbeVerdict.SAFE

    def test_an_uncompilable_pattern_falls_back_to_a_literal_test(self) -> None:
        """An unbalanced group is not a Python regex; the text is still there."""
        assert _only('pgrep -f "run_02("').verdict is ProbeVerdict.SELF_MATCHING

    def test_a_dot_metacharacter_still_matches_its_own_text(self) -> None:
        assert _only('pgrep -f "run.02"').verdict is ProbeVerdict.SELF_MATCHING


class TestBracketTrick:
    """The rewrite helper the deny message quotes back at the caller."""

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("run_02", "[r]un_02"),
            ("nginx", "[n]ginx"),
            ("2fa-worker", "[2]fa-worker"),
            ("_leading", "[_]leading"),
        ],
    )
    def test_brackets_the_first_character(self, pattern: str, expected: str) -> None:
        assert bracket_trick(pattern) == expected

    @pytest.mark.parametrize(
        "pattern",
        [
            "",
            # Already tricked — bracketing again would be noise.
            "[r]un_02",
            # A leading metacharacter is part of the regex, not a literal to hide.
            ".*run",
            "^run_02",
        ],
    )
    def test_refuses_patterns_it_cannot_safely_rewrite(self, pattern: str) -> None:
        assert bracket_trick(pattern) is None


class TestIncidentCorpus:
    """The exact deny/allow corpus from the imported incident report."""

    @pytest.mark.parametrize(
        "command",
        [
            'until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done',
            "while pgrep -af 'provisioner playbooks/' ; do sleep 5; done",
            'pkill -f "my-long-job"',
            'ps aux | grep "provisioner" | wc -l',
        ],
    )
    def test_the_deny_corpus_is_self_matching(self, command: str) -> None:
        probes = classify_process_probes(command)
        assert probes
        assert any(probe.is_self_matching for probe in probes)

    @pytest.mark.parametrize(
        "command",
        [
            "pgrep -f '[p]rovision.bash'",
            'pgrep -f -- "[p]rovision.bash"',
            "pgrep -x provisioner",
            "ps aux | grep '[p]rovision'",
            "ps aux | grep provision | grep -v grep",
            './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done',
            'until grep -q "PLAY RECAP" run.log; do sleep 10; done',
        ],
    )
    def test_the_allow_corpus_is_never_self_matching(self, command: str) -> None:
        assert not any(probe.is_self_matching for probe in classify_process_probes(command))

    def test_a_variable_pattern_is_unresolved_not_self_matching(self) -> None:
        probes = classify_process_probes('pgrep -f "$pattern"')
        assert [probe.verdict for probe in probes] == [ProbeVerdict.UNRESOLVED]

    def test_the_reported_rewrite_is_the_one_offered(self) -> None:
        probe = _only('until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done')
        assert probe.safe_rewrite == 'pgrep -f "[p]rovision.bash target-host"'


class TestLivenessLoops:
    """A wait loop is a second thing that can lie, independently of the probe."""

    def test_no_loop_means_no_report(self) -> None:
        assert classify_liveness_loops("pgrep -f run_02") == ()
        assert classify_liveness_loops("") == ()

    def test_a_for_loop_is_not_a_liveness_wait(self) -> None:
        """Its iteration count is a fixed list, so it cannot spin for ever."""
        assert classify_liveness_loops("for i in 1 2 3; do sleep 1; done") == ()

    @pytest.mark.parametrize(
        "command",
        [
            _INCIDENT,
            'until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done',
            "while pgrep -af 'provisioner playbooks/' ; do sleep 5; done",
            # A PID probe is honest, but the loop around it is still uncapped.
            './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done',
        ],
    )
    def test_a_probe_conditioned_sleep_loop_is_unbounded(self, command: str) -> None:
        loops = classify_liveness_loops(command)
        assert len(loops) == 1
        assert loops[0].is_unbounded_liveness_wait is True

    def test_waiting_on_an_artefact_is_never_flagged(self) -> None:
        """This is the remedy the report recommends; flagging it would be wrong."""
        loops = classify_liveness_loops('until grep -q "PLAY RECAP" run.log; do sleep 10; done')
        assert len(loops) == 1
        assert loops[0].probes == ()
        assert loops[0].is_unbounded_liveness_wait is False

    def test_a_counter_in_the_body_bounds_the_loop(self) -> None:
        command = "until ! pgrep -f run_02; do sleep 5; i=$((i+1)); done"
        loops = classify_liveness_loops(command)
        assert loops[0].bounded is True
        assert loops[0].is_unbounded_liveness_wait is False

    def test_a_numeric_cap_in_the_condition_bounds_the_loop(self) -> None:
        command = 'while pgrep -f run_02 && [ "$i" -lt 60 ]; do sleep 5; done'
        assert classify_liveness_loops(command)[0].bounded is True

    def test_a_working_body_is_not_an_idle_spin(self) -> None:
        command = "until ! pgrep -f run_02; do sleep 5; ./collect-metrics.sh; done"
        loops = classify_liveness_loops(command)
        assert loops[0].body_only_sleeps is False
        assert loops[0].is_unbounded_liveness_wait is False

    def test_an_echo_beside_the_sleep_still_counts_as_idle(self) -> None:
        command = "until ! pgrep -f run_02; do echo waiting; sleep 5; done"
        assert classify_liveness_loops(command)[0].body_only_sleeps is True

    def test_the_loop_records_its_own_parts(self) -> None:
        loops = classify_liveness_loops(_INCIDENT)
        assert loops[0].keyword == "until"
        assert "pgrep" in loops[0].condition
        assert loops[0].body.strip() == "sleep 30"
        assert loops[0].text == _INCIDENT

    def test_a_loop_hidden_in_a_quoted_script_is_not_reported(self) -> None:
        """Those shapes are the BOUNDED ones, so reporting them advises against the fix."""
        command = "timeout 3600 bash -c 'until ! pgrep -f run_02; do sleep 5; done'"
        assert classify_liveness_loops(command) == ()

    def test_two_loops_are_both_described(self) -> None:
        command = (
            "until ! pgrep -f run_01; do sleep 5; done; "
            "until grep -q done run.log; do sleep 5; done"
        )
        loops = classify_liveness_loops(command)
        assert [loop.is_unbounded_liveness_wait for loop in loops] == [True, False]


class TestWrapperPidWaits:
    """`$!` after a wrapper names the WRAPPER, not the job (Rule B).

    The incident's first waiter. `setsid nohup ./job … &` makes `$!` the pid of
    `setsid`, which forks and whose parent exits in milliseconds — so
    `kill -0 $!` reported "finished" while the job was in its fourth minute.
    """

    _SETSID = (
        "setsid nohup ./job.bash > j.log 2>&1 & sleep 1; " "until ! kill -0 $! ; do sleep 5; done"
    )

    def _only(self, command: str) -> WrapperPidWait:
        waits = classify_wrapper_pid_waits(command)
        assert len(waits) == 1, f"expected exactly one wait in {command!r}, got {waits!r}"
        return waits[0]

    def test_the_incident_waiter_names_setsid(self) -> None:
        wait = self._only(self._SETSID)
        assert wait.wrapper == "setsid"
        assert wait.reference == "$!"

    def test_setsid_detaches_so_the_pid_is_already_gone(self) -> None:
        assert self._only(self._SETSID).detaching is True

    def test_the_incident_waiter_sits_inside_a_loop(self) -> None:
        assert self._only(self._SETSID).wait_construct is WaitConstruct.LOOP

    def test_the_job_text_is_reported_back(self) -> None:
        assert self._only(self._SETSID).job.startswith("setsid nohup ./job.bash")

    @pytest.mark.parametrize(
        "command",
        [
            # The allow corpus: no wrapper at all, so `$!` IS the job's pid.
            './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done',
            # `nohup` execs in place when it is handed a command rather than a
            # shell script, so the pid it was given is the pid that runs.
            "nohup ./job.bash & pid=$!",
            "nohup ./job.bash > j.log 2>&1 & until ! kill -0 $!; do sleep 5; done",
            # `setsid -w` waits for its child, so the wrapper outlives the job
            # and `$!` tracks it honestly.
            "setsid -w ./job.bash & wait $!",
            "setsid --wait ./job.bash & wait $!",
            # No background job in this command, so `$!` binds to nothing here.
            "wait $!",
            "kill -0 $!",
            # The reference comes BEFORE the job it would have to name.
            "wait $!; setsid ./job.bash &",
            # Prose: one quoted argument, so bash never sees a `&` operator.
            'echo "setsid ./job.bash & kill -0 $!"',
        ],
    )
    def test_shapes_with_no_wrapper_pid_hazard(self, command: str) -> None:
        assert classify_wrapper_pid_waits(command) == ()

    @pytest.mark.parametrize(
        ("command", "wrapper"),
        [
            ("nohup sh -c './job.bash > j.log 2>&1' & wait $!", "nohup sh -c"),
            ("nohup bash -c './job.bash' & wait $!", "nohup bash -c"),
            ("timeout 600 ./job.bash & wait $!", "timeout"),
            ("env FOO=1 ./job.bash & wait $!", "env"),
        ],
    )
    def test_a_forking_wrapper_is_named_but_does_not_detach(
        self, command: str, wrapper: str
    ) -> None:
        wait = self._only(command)
        assert wait.wrapper == wrapper
        assert wait.detaching is False

    @pytest.mark.parametrize(
        "command",
        [
            "env FOO=1 setsid ./job.bash & wait $!",
            "nohup setsid ./job.bash & wait $!",
            "timeout 600 setsid ./job.bash & wait $!",
        ],
    )
    def test_setsid_behind_another_wrapper_still_decides(self, command: str) -> None:
        wait = self._only(command)
        assert wait.wrapper == "setsid"
        assert wait.detaching is True

    @pytest.mark.parametrize(
        "command",
        [
            "setsid ./job.bash & wait $!",
            "setsid ./job.bash & kill -0 $!",
            "setsid ./job.bash & ps -p $!",
            'setsid ./job.bash & ps -o pid= -p "$!"',
        ],
    )
    def test_every_probe_command_is_a_use_site(self, command: str) -> None:
        assert self._only(command).detaching is True

    def test_a_captured_pid_is_followed_through_its_variable(self) -> None:
        command = 'setsid ./job.bash & pid=$!; until ! kill -0 "$pid"; do sleep 5; done'
        wait = self._only(command)
        assert wait.reference == "$pid"
        assert wait.wait_construct is WaitConstruct.LOOP

    def test_a_braced_reference_is_followed_too(self) -> None:
        command = "setsid ./job.bash & job_pid=$!; wait ${job_pid}"
        assert self._only(command).reference == "$job_pid"

    def test_an_unrelated_variable_is_not_followed(self) -> None:
        """`$other` was never assigned from `$!`, so it names nothing here."""
        assert classify_wrapper_pid_waits('setsid ./job.bash & kill -0 "$other"') == ()

    def test_a_loop_keyed_on_the_pid_counts_without_a_probe_command(self) -> None:
        """`a loop keyed on $!` is the shape, whatever the condition runs."""
        command = "setsid ./job.bash & while [ -d /proc/$! ]; do sleep 5; done"
        wait = self._only(command)
        assert wait.wait_construct is WaitConstruct.LOOP
        assert wait.reference == "$!"

    def test_a_probe_inside_a_loop_is_reported_once(self) -> None:
        """The span pass and the loop pass must not both claim the same site."""
        command = "setsid ./job.bash & until ! kill -0 $!; do sleep 5; done"
        assert len(classify_wrapper_pid_waits(command)) == 1

    def test_two_uses_are_both_reported(self) -> None:
        command = "setsid ./job.bash & pid=$!; kill -0 $pid; wait $pid"
        waits = classify_wrapper_pid_waits(command)
        assert [wait.reference for wait in waits] == ["$pid", "$pid"]

    def test_a_later_job_owns_a_later_reference(self) -> None:
        """`$!` names the MOST RECENT background job, so the second one wins."""
        command = "./safe.bash & wait $!; setsid ./job.bash & wait $!"
        waits = classify_wrapper_pid_waits(command)
        assert len(waits) == 1
        assert waits[0].wrapper == "setsid"

    def test_a_one_shot_use_records_no_wait_construct(self) -> None:
        assert self._only("setsid ./job.bash & wait $!").wait_construct is None

    def test_an_empty_command_reports_nothing(self) -> None:
        assert classify_wrapper_pid_waits("") == ()
        assert classify_wrapper_pid_waits("   ") == ()
