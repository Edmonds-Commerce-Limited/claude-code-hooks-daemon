"""Corpus tests for the long-running command classifier (Plan 00602).

Three corpora: commands that must be DENIED (a wait, a long timeout, or a
known-slow program), commands that must draw only the no-timeout ADVISORY, and
commands that must draw NOTHING. The real shapes from the session that
prompted the plan are in the first corpus.
"""

from __future__ import annotations

import re

import pytest

from claude_code_hooks_daemon.utils.long_running_command import (
    BUILD_PATTERNS,
    CONTAINER_PATTERNS,
    DEFAULT_SLOW_PATTERNS,
    DEFAULT_THRESHOLD_SECONDS,
    INSTALL_PATTERNS,
    MAKE_PATTERNS,
    QA_PATTERNS,
    TEST_PATTERNS,
    WATCH_PATTERNS,
    FindingKind,
    LongRunningPolicy,
    classify,
    parse_duration_seconds,
)

POLICY = LongRunningPolicy()

DENY_CORPUS: list[tuple[str, FindingKind]] = [
    # The shape from the prompting session.
    (
        "timeout 590 bash -c 'until gh run list --branch plan-1 --json status "
        "| grep -q completed; do sleep 30; done'",
        FindingKind.WAIT_LOOP,
    ),
    (
        "timeout 590 bash -c 'until gh run list --branch plan-1 --json status "
        "| grep -q completed; do sleep 30; done'",
        FindingKind.LONG_TIMEOUT,
    ),
    ("until test -f /tmp/ready; do sleep 5; done", FindingKind.WAIT_LOOP),
    ("while true; do curl -s localhost:8080; sleep 2; done", FindingKind.WAIT_LOOP),
    ("while ! test -f /tmp/x\ndo\n  sleep 1\ndone", FindingKind.WAIT_LOOP),
    ("sleep 60", FindingKind.LONG_SLEEP),
    ("sleep 2m", FindingKind.LONG_SLEEP),
    ("sleep 31 && echo done", FindingKind.LONG_SLEEP),
    ("timeout 120 curl https://example.com/slow", FindingKind.LONG_TIMEOUT),
    ("FOO=1 timeout -k 5 120 pytest tests", FindingKind.LONG_TIMEOUT),
    ("timeout 5m make", FindingKind.LONG_TIMEOUT),
    ("timeout --kill-after=10 600 ./run.sh", FindingKind.LONG_TIMEOUT),
    (
        "./scripts/qa/llm_qa.py changed --base main --allow-unmapped",
        FindingKind.SLOW_COMMAND,
    ),
    ("pytest tests/unit -q", FindingKind.SLOW_COMMAND),
    ("uv run python3 -m pytest tests/unit -q", FindingKind.SLOW_COMMAND),
    ("python -m pytest", FindingKind.SLOW_COMMAND),
    (".venv/bin/pytest tests", FindingKind.SLOW_COMMAND),
    ("cd tests && pytest -q", FindingKind.SLOW_COMMAND),
    ("gh run watch 123456", FindingKind.SLOW_COMMAND),
    ("gh pr checks 12 --watch", FindingKind.SLOW_COMMAND),
    ("npm ci", FindingKind.SLOW_COMMAND),
    ("pip install -r requirements.txt", FindingKind.SLOW_COMMAND),
    ("cargo build --release", FindingKind.SLOW_COMMAND),
    ("docker build .", FindingKind.SLOW_COMMAND),
    ("./scripts/qa/run_all.sh", FindingKind.SLOW_COMMAND),
    ("make test", FindingKind.SLOW_COMMAND),
]

ADVISE_CORPUS: list[str] = [
    "python3 scripts/analyse.py",
    "curl -s https://example.com/x",
    "git fetch origin",
    "git push origin main",
    "git pull --ff-only",
    "git clone https://example.com/x.git",
    "git -C sub fetch --all",
    "./scripts/something.sh --flag",
    "python3 -c 'print(1)'",
    "cd /work && ./build-docs.sh",
]

ALLOW_CORPUS: list[str] = [
    "git status",
    "git log --oneline -5",
    "git diff --stat",
    "ls -la",
    "cat README.md",
    "grep -rn foo src",
    "gh pr view 3 --comments",
    "gh issue list --limit 5",
    "sleep 2",
    "sleep 30",
    "timeout 20 curl https://example.com/x",
    "timeout 30 ls src",
    "timeout 20 pytest tests/unit/test_one.py",
    "git commit -m 'timeout 590 pytest; sleep 60; until x; do sleep 30; done'",
    'echo "until x; do sleep 30; done"',
    "grep -n timeout src/x.py",
    "grep -rn 'pytest' docs",
    "cat > notes.md <<'EOF'\nrun pytest tests and sleep 60\nEOF",
    "nohup pytest tests > out.txt 2>&1 &",
    "timeout 590 bash -c 'until test -f x; do sleep 30; done' &",
    "cd /x && git status",
    "set -euo pipefail; git status; git diff",
    "while read line; do echo $line; done < f.txt",
    "for f in a b; do echo $f; done",
    "echo pytest",
    "mkdir -p untracked/scratch && touch untracked/scratch/x",
    "bin/hooks-daemon status",
    "git add -A && git commit -m 'x'",
    "git mv a b && git commit -m 'move'",
    "git merge --no-ff topic",
    "git rev-parse HEAD",
    "git worktree list",
    "git show HEAD~1 --stat",
    "git branch --show-current",
    "git -C sub status",
    "CLAUDE/Plan/mkplan.bash my-plan",
    "mkplan.bash --journal plan cat body.md",
    "pingbus send peer hello",
    "rg -n foo src",
    "jq .a file.json",
    "awk 'NR<3' file",
    "gh pr view 3 --json state",
]


@pytest.mark.parametrize(("command", "kind"), DENY_CORPUS)
def test_deny_corpus_finds_kind(command: str, kind: FindingKind) -> None:
    kinds = {finding.kind for finding in classify(command, POLICY)}
    assert kind in kinds


@pytest.mark.parametrize(("command", "kind"), DENY_CORPUS)
def test_deny_corpus_is_never_only_advisory(command: str, kind: FindingKind) -> None:
    findings = classify(command, POLICY)
    assert any(finding.kind is not FindingKind.UNBOUNDED for finding in findings)


@pytest.mark.parametrize("command", ADVISE_CORPUS)
def test_advise_corpus_is_only_unbounded(command: str) -> None:
    kinds = {finding.kind for finding in classify(command, POLICY)}
    assert kinds == {FindingKind.UNBOUNDED}


@pytest.mark.parametrize("command", ALLOW_CORPUS)
def test_allow_corpus_draws_nothing(command: str) -> None:
    assert classify(command, POLICY) == ()


class TestThreshold:
    def test_default_is_thirty_seconds(self) -> None:
        assert DEFAULT_THRESHOLD_SECONDS == 30

    def test_raised_threshold_allows_a_longer_sleep(self) -> None:
        policy = LongRunningPolicy(threshold_seconds=120)
        assert classify("sleep 60", policy) == ()

    def test_raised_threshold_allows_a_longer_timeout(self) -> None:
        policy = LongRunningPolicy(threshold_seconds=120)
        assert classify("timeout 100 curl https://example.com", policy) == ()

    def test_wait_loop_is_denied_whatever_the_threshold(self) -> None:
        policy = LongRunningPolicy(threshold_seconds=100000)
        kinds = {f.kind for f in classify("until test -f x; do sleep 1; done", policy)}
        assert FindingKind.WAIT_LOOP in kinds


class TestPolicyLists:
    def test_extra_slow_pattern_flags_a_project_command(self) -> None:
        policy = LongRunningPolicy.build(extra_slow_patterns=[r"^deploy\.sh\b"])
        kinds = {f.kind for f in classify("./deploy.sh prod", policy)}
        assert kinds == {FindingKind.SLOW_COMMAND}

    def test_extra_fast_program_silences_the_advisory(self) -> None:
        policy = LongRunningPolicy.build(extra_fast_programs=["mytool"])
        assert classify("mytool --version", policy) == ()

    def test_extra_fast_program_does_not_silence_network_git(self) -> None:
        policy = LongRunningPolicy.build(extra_fast_programs=["git"])
        kinds = {f.kind for f in classify("git push origin main", policy)}
        assert kinds == {FindingKind.UNBOUNDED}

    def test_fast_program_never_hides_a_deny(self) -> None:
        policy = LongRunningPolicy.build(extra_fast_programs=["mkplan.bash", "pingbus"])
        assert {f.kind for f in classify("sleep 60", policy)} == {FindingKind.LONG_SLEEP}
        assert FindingKind.LONG_TIMEOUT in {
            f.kind for f in classify("timeout 600 pingbus wait", policy)
        }

    def test_exempt_pattern_silences_everything_it_matches(self) -> None:
        policy = LongRunningPolicy.build(exempt_patterns=[r"^pytest tests/unit/test_one\.py"])
        assert classify("pytest tests/unit/test_one.py", policy) == ()

    def test_bad_regex_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid regex"):
            LongRunningPolicy.build(extra_slow_patterns=["("])


class TestParseDuration:
    @pytest.mark.parametrize(
        ("word", "seconds"),
        [("5", 5.0), ("5s", 5.0), ("2m", 120.0), ("1h", 3600.0), ("1d", 86400.0), ("1.5", 1.5)],
    )
    def test_parses(self, word: str, seconds: float) -> None:
        assert parse_duration_seconds(word) == seconds

    @pytest.mark.parametrize("word", ["", "abc", "$N", "-5", "5x"])
    def test_unparseable_is_none(self, word: str) -> None:
        assert parse_duration_seconds(word) is None

    def test_zero_timeout_style_infinity_is_not_special_here(self) -> None:
        assert parse_duration_seconds("0") == 0.0


class TestFindingDetail:
    def test_timeout_finding_names_the_seconds(self) -> None:
        finding, *_rest = classify("timeout 120 curl https://example.com/slow", POLICY)
        assert "120" in finding.subject

    def test_slow_finding_names_the_program(self) -> None:
        finding, *_rest = classify("pytest tests", POLICY)
        assert "pytest" in finding.subject

    def test_findings_are_deduplicated(self) -> None:
        findings = classify("pytest a; pytest b", POLICY)
        assert len(findings) == len(set(findings))


#: Shapes the classifier read as short or harmless although they block the session.
MISSED_SHAPES: list[tuple[str, FindingKind]] = [
    # N-11: a trailing `&` backgrounds only the last statement of a `;` list.
    ("sleep 300; echo x &", FindingKind.LONG_SLEEP),
    ("pytest tests/; true &", FindingKind.SLOW_COMMAND),
    ("sleep 300\necho x &", FindingKind.LONG_SLEEP),
    ("sleep 5 & sleep 100; echo x &", FindingKind.LONG_SLEEP),
    # N-12: never-ending and wrapped long shapes.
    ("tail -f log", FindingKind.SLOW_COMMAND),
    ("tail -n 5 -F log", FindingKind.SLOW_COMMAND),
    ("tail --follow=name log", FindingKind.SLOW_COMMAND),
    ("sleep infinity", FindingKind.LONG_SLEEP),
    ('bash -c "sleep 100"', FindingKind.LONG_SLEEP),
    ("sh -c 'pytest tests/unit'", FindingKind.SLOW_COMMAND),
    ("(sleep 100)", FindingKind.LONG_SLEEP),
    ("( pytest tests/unit )", FindingKind.SLOW_COMMAND),
    ("sleep 100 & wait", FindingKind.SLOW_COMMAND),
    # T-13: a leading redirect does not hide the command.
    (">out.txt pytest tests/", FindingKind.SLOW_COMMAND),
    ("> out.txt pytest tests/", FindingKind.SLOW_COMMAND),
    ("2>err.txt sleep 100", FindingKind.LONG_SLEEP),
]


@pytest.mark.parametrize(("command", "kind"), MISSED_SHAPES)
def test_missed_shape_is_found(command: str, kind: FindingKind) -> None:
    assert kind in {finding.kind for finding in classify(command, POLICY)}


@pytest.mark.parametrize(
    "command",
    [
        "(sleep 2)",
        "sleep 100 &",
        "(sleep 100) &",
        "echo a; sleep 100 &",
        "pytest tests/ && echo done &",
        "sleep 100 && echo x &",
        "until test -f x; do sleep 5; done &",
        "pytest tests/ | cat &",
        "tail -f log &",
        "timeout 20 tail -f log",
        "tail -n 5 log",
        "bash -c 'git status'",
    ],
)
def test_still_allowed_after_the_corrections(command: str) -> None:
    kinds = {finding.kind for finding in classify(command, POLICY)}
    assert kinds <= {FindingKind.UNBOUNDED}


class TestPatternGroups:
    """Plan 00635: the slow list is named groups, so a guard can take a subset."""

    def test_default_is_every_group_in_order(self) -> None:
        assert DEFAULT_SLOW_PATTERNS == (
            *TEST_PATTERNS,
            *BUILD_PATTERNS,
            *MAKE_PATTERNS,
            *QA_PATTERNS,
            *INSTALL_PATTERNS,
            *CONTAINER_PATTERNS,
            *WATCH_PATTERNS,
        )

    @pytest.mark.parametrize(
        ("command", "group"),
        [
            ("pytest tests/", TEST_PATTERNS),
            ("npm test", TEST_PATTERNS),
            ("npm run test:unit", TEST_PATTERNS),
            ("cargo test", TEST_PATTERNS),
            ("go test ./...", TEST_PATTERNS),
            ("npm run build", BUILD_PATTERNS),
            ("cargo clippy", BUILD_PATTERNS),
            ("uv build", BUILD_PATTERNS),
            ("tsc -p .", BUILD_PATTERNS),
            ("make", MAKE_PATTERNS),
            ("llm_qa.py all", QA_PATTERNS),
            ("npm install", INSTALL_PATTERNS),
            ("cargo install ripgrep", INSTALL_PATTERNS),
            ("pip install x", INSTALL_PATTERNS),
            ("docker compose up", CONTAINER_PATTERNS),
            ("gh run watch 1", WATCH_PATTERNS),
        ],
    )
    def test_each_shape_sits_in_one_group(self, command: str, group: tuple[str, ...]) -> None:
        groups = (
            TEST_PATTERNS,
            BUILD_PATTERNS,
            MAKE_PATTERNS,
            QA_PATTERNS,
            INSTALL_PATTERNS,
            CONTAINER_PATTERNS,
            WATCH_PATTERNS,
        )
        hits = [g for g in groups if any(re.search(p, command) for p in g)]
        assert hits == [group]


@pytest.mark.parametrize(
    "command",
    ["nice -n 19 pytest tests/", "ionice -c 3 pytest", "sudo -u ci pytest", "nice -n 19 make"],
)
def test_wrapper_option_values_are_peeled(command: str) -> None:
    """Plan 00635: `nice -n 19 pytest` ran `19`, so the slow test run went unseen."""
    kinds = {finding.kind for finding in classify(command, POLICY)}
    assert FindingKind.SLOW_COMMAND in kinds


@pytest.mark.parametrize(
    "command",
    [
        '"pytest" tests/',
        "'pytest' tests/",
        "p\\ytest tests/",
        '"/usr/bin/pytest" -x',
        "env FOO=1 'pytest'",
        'nice -n 19 "pytest" tests/',
        "'sleep' 600",
    ],
)
def test_quoted_program_name_is_classified_like_the_bare_one(command: str) -> None:
    """Plan 00635 review: quoting the program word ran the same command unseen."""
    assert classify(command, POLICY, include_background=True)


@pytest.mark.parametrize("command", ["command -v pytest", "command -V make", "command -pv make"])
def test_command_lookup_is_not_a_run(command: str) -> None:
    kinds = {finding.kind for finding in classify(command, POLICY)}
    assert FindingKind.SLOW_COMMAND not in kinds


#: Spellings only a deep-peel policy (host_seat_lane_guard) reads through.
DEEP_ONLY = [
    "xargs pytest < f",
    "eval 'pytest tests'",
    "taskset -c 0 pytest",
    "flock /tmp/l pytest",
    "script -qc pytest /dev/null",
    "stdbuf -o L pytest",
    "exec -a x pytest",
    "env -C /x pytest",
    "sudo -T 5 pytest",
]


class TestDeepPeel:
    """Plan 00635 review finding 6: the shared default must not peel further.

    long_running_command_guard denies a SLOW_COMMAND in the foreground, so
    reading through one more wrapper in the default policy turns its advisory
    into a deny for every session. Only a policy built with ``deep_peel`` does.
    """

    def test_default_policy_does_not_deep_peel(self) -> None:
        assert LongRunningPolicy().deep_peel is False
        assert LongRunningPolicy.build().deep_peel is False

    @pytest.mark.parametrize("command", DEEP_ONLY)
    def test_default_policy_leaves_the_spelling_unread(self, command: str) -> None:
        kinds = {finding.kind for finding in classify(command, POLICY)}
        assert FindingKind.SLOW_COMMAND not in kinds

    @pytest.mark.parametrize("command", DEEP_ONLY)
    def test_deep_policy_reads_through_it(self, command: str) -> None:
        policy = LongRunningPolicy(deep_peel=True)
        kinds = {finding.kind for finding in classify(command, policy)}
        assert FindingKind.SLOW_COMMAND in kinds


class TestIncludeBackground:
    """Plan 00635: a lane guard judges backgrounded work too."""

    @pytest.mark.parametrize("command", ["pytest tests/ &", "echo a; pytest &", "pytest | cat &"])
    def test_background_is_skipped_by_default(self, command: str) -> None:
        kinds = {finding.kind for finding in classify(command, POLICY)}
        assert FindingKind.SLOW_COMMAND not in kinds

    @pytest.mark.parametrize("command", ["pytest tests/ &", "echo a; pytest &", "pytest | cat &"])
    def test_background_is_judged_when_asked(self, command: str) -> None:
        findings = classify(command, POLICY, include_background=True)
        assert FindingKind.SLOW_COMMAND in {finding.kind for finding in findings}

    def test_no_wait_finding_when_background_is_judged(self) -> None:
        findings = classify("echo a & wait", POLICY, include_background=True)
        assert all(finding.subject != "wait for a background job" for finding in findings)
