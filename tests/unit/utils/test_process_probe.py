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
    bracket_trick,
    classify_process_probes,
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

    def test_one_shot_probe_has_no_wait_construct(self) -> None:
        assert _only("pgrep -f run_02").wait_construct is None

    def test_gated_probe_is_still_one_shot(self) -> None:
        """`&&` runs the next command once; it does not wait."""
        assert _only("pgrep -f run_02 && echo found").wait_construct is None


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
