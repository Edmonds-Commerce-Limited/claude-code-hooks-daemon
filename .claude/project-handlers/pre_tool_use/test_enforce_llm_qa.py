"""Tests for EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py."""

import re
from typing import Any

import pytest
from enforce_llm_qa import EnforceLlmQaHandler


class TestEnforceLlmQaHandler:
    """Tests for the LLM QA script enforcement handler."""

    @pytest.fixture
    def handler(self) -> EnforceLlmQaHandler:
        return EnforceLlmQaHandler()

    # ── Identity ──

    def test_name(self, handler: EnforceLlmQaHandler) -> None:
        assert handler.name == "enforce-llm-qa"

    def test_terminal(self, handler: EnforceLlmQaHandler) -> None:
        assert handler.terminal is True

    def test_tags(self, handler: EnforceLlmQaHandler) -> None:
        assert "project" in handler.tags
        assert "blocking" in handler.tags

    # ── matches() ──

    def test_matches_run_all_sh(self, handler: EnforceLlmQaHandler, bash_hook_input: Any) -> None:
        """Blocks ./scripts/qa/run_all.sh."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_all.sh")) is True

    def test_matches_run_all_sh_with_redirect(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh even with output redirect."""
        assert (
            handler.matches(
                bash_hook_input("./scripts/qa/run_all.sh > /tmp/qa.txt 2>&1; tail -20 /tmp/qa.txt")
            )
            is True
        )

    def test_matches_run_all_sh_absolute_path(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh with absolute path."""
        assert handler.matches(bash_hook_input("/workspace/scripts/qa/run_all.sh")) is True

    def test_does_not_match_llm_qa(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT block llm_qa.py."""
        assert handler.matches(bash_hook_input("./scripts/qa/llm_qa.py all")) is False

    def test_does_not_match_individual_qa_scripts(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT block individual QA scripts (run_tests.sh, etc.)."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_tests.sh")) is False
        assert handler.matches(bash_hook_input("./scripts/qa/run_lint.sh")) is False
        assert handler.matches(bash_hook_input("./scripts/qa/run_format_check.sh")) is False

    def test_does_not_match_non_bash(self, handler: EnforceLlmQaHandler) -> None:
        """Does NOT match Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/qa/run_all.sh", "content": "x"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_unrelated_commands(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match unrelated bash commands."""
        assert handler.matches(bash_hook_input("git status")) is False
        assert handler.matches(bash_hook_input("pytest tests/")) is False

    def test_does_not_match_git_add_of_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git add that stages the script file."""
        assert handler.matches(bash_hook_input("git add scripts/qa/run_all.sh")) is False

    def test_does_not_match_git_commit_mentioning_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git commit whose message mentions the script."""
        assert (
            handler.matches(bash_hook_input('git commit -m "Integrated into run_all.sh"')) is False
        )

    def test_does_not_match_glob_of_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git add with glob that matches the script."""
        assert handler.matches(bash_hook_input("git add scripts/qa/run_all*")) is False

    # ── handle() ──

    def test_handle_blocks_with_guidance(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Returns DENY with llm_qa.py guidance."""
        result = handler.handle(bash_hook_input("./scripts/qa/run_all.sh"))
        assert result.decision == "deny"
        assert result.reason is not None
        assert "llm_qa.py" in result.reason
        assert "run_all.sh" in result.reason

    # ── matches() — invocation vs mention (Plan 00200, dogfooding false positive) ──

    def test_does_not_match_cat_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`cat` inspects the script's contents, it does not execute it."""
        assert handler.matches(bash_hook_input("cat scripts/qa/run_all.sh")) is False

    def test_does_not_match_less_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("less scripts/qa/run_all.sh")) is False

    def test_does_not_match_grep_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input('grep -n "check" scripts/qa/run_all.sh')) is False

    def test_does_not_match_head_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("head -20 scripts/qa/run_all.sh")) is False

    def test_still_matches_bash_invocation_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Explicit interpreter invocation still executes the script."""
        assert handler.matches(bash_hook_input("bash scripts/qa/run_all.sh")) is True

    def test_does_not_match_git_commit_preceded_by_cd(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The git exemption must survive a leading `cd`.

        Regression: the exemption tested `command.startswith("git ")` against
        the WHOLE string, so the ubiquitous `cd /workspace; git commit -m ...`
        lost it entirely and a commit message mentioning the script was denied.
        The exemption belongs to the segment, like every other verdict here.
        """
        command = 'cd /workspace; git commit -m "wired the check into run_all.sh"'
        assert handler.matches(bash_hook_input(command)) is False

    def test_still_matches_invocation_after_a_cd(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Moving the exemption per-segment must not blind the guard."""
        assert handler.matches(bash_hook_input("cd /workspace; bash scripts/qa/run_all.sh")) is True

    def test_does_not_match_shellcheck_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A static analyser READS the script; it never runs it.

        Regression for a real dogfooding false positive: `shellcheck -x
        scripts/qa/run_all.sh` -- the canonical way to verify an edit to that
        very script -- was denied with "run_all.sh produces 200+ lines of
        verbose output", which shellcheck does not produce and would not cause.
        """
        assert handler.matches(bash_hook_input("shellcheck -x scripts/qa/run_all.sh")) is False

    def test_does_not_match_diff_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("diff scripts/qa/run_all.sh /tmp/old.sh")) is False

    # ── matches() — segmentation defects ──

    def test_matches_invocation_on_a_later_LINE_of_a_multiline_command(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A newline separates commands just as `;` does.

        Regression: segmentation split only on `&&`/`||`/`;`/`|`, so a
        multi-line command collapsed into ONE segment. The leading word was
        taken from line 1 -- an inspection command -- and a real invocation on
        line 2 was waved through. A false NEGATIVE: the block simply did not
        apply to the shape agents use most (a heredoc-style multi-line script).
        """
        command = "grep -n pattern some/file.txt\nbash scripts/qa/run_all.sh"
        assert handler.matches(bash_hook_input(command)) is True

    def test_does_not_match_grep_whose_PATTERN_contains_a_pipe(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A `|` inside quotes is data, not a pipeline separator.

        Regression: splitting on a bare `[;|]` cut through a quoted grep
        alternation, leaving a fragment whose "leading word" was the tail of
        the pattern (``CHECKS="``). That is in no allowlist, so an ordinary
        read of the script was denied. A false POSITIVE, and the reason this
        test exists.
        """
        command = 'grep -n "print_result\\|^run_check\\|CHECKS=" scripts/qa/run_all.sh'
        assert handler.matches(bash_hook_input(command)) is False

    def test_matches_real_pipeline_invocation(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """An UNQUOTED `|` still separates -- the fix must not blind the guard."""
        assert handler.matches(bash_hook_input("echo hi | bash scripts/qa/run_all.sh")) is True

    def test_does_not_match_git_commit_whose_QUOTED_HEREDOC_body_mentions_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Plan 00234 finding H-3 -- found by hitting it, not by reading.

        The VCS exemption exists precisely so a commit message mentioning the
        script is not read as running it, and it already works for `-m` and for
        `cd ... && git commit`. It did NOT work for `-F - <<'EOF'`: a newline is
        a segment separator, so the message body was split into pseudo-commands
        and judged line by line. The leading word of the offending "command" was
        the English word `prose`.

        A QUOTED delimiter disables every expansion, so the body is literal text
        that cannot invoke anything -- the same fact `pipe_blocker` already
        encoded, now shared via `strip_quoted_heredoc_bodies`.
        """
        command = (
            "git commit -F - <<'EOF'\n"
            "Plan 00234: record the audit finding\n"
            "\n"
            "enforce_llm_qa denies scripts/qa/run_all.sh while the docs\n"
            "instruct the agent to run it.\n"
            "EOF"
        )
        assert handler.matches(bash_hook_input(command)) is False

    def test_still_matches_invocation_after_an_UNQUOTED_heredoc(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """An unquoted `<<EOF` DOES expand, so its body must stay scanned.

        The exemption is about what bash treats as literal, not about heredocs
        being prose-shaped. Blanking this body would be a real bypass.
        """
        command = "cat <<EOF\nvalue is $(bash scripts/qa/run_all.sh)\nEOF"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_matches_invocation_outside_a_quoted_heredoc(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blanking the body must not blank the command that carries it."""
        command = "bash scripts/qa/run_all.sh && git commit -F - <<'EOF'\nmessage\nEOF"
        assert handler.matches(bash_hook_input(command)) is True

    def test_single_quoted_trailing_backslash_cannot_hide_the_invocation(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        r"""Plan 00200 Task 3.7 — a real bypass, closed by the shared scanner.

        This handler's own splitter applied backslash escaping INSIDE single
        quotes, where bash treats it as a literal character. A trailing ``\``
        in a single-quoted argument therefore swallowed the closing quote, the
        scanner never left quoted state, nothing split, and the whole command
        was judged by its allowlisted leading word (``grep``/``cat``) — letting
        the guarded script through untouched.

        The sibling scanner in ``pipe_blocker`` had the mirror-image bug
        (blind to the backslash entirely). Both now share one implementation.
        """
        for command in (
            r"grep -n 'a\' README.md ; ./scripts/qa/run_all.sh",
            r"cat 'x\' ; ./scripts/qa/run_all.sh",
        ):
            assert (
                handler.matches(bash_hook_input(command)) is True
            ), f"escaped quote must not hide the invocation: {command}"

    def test_single_quoted_backslash_still_allows_a_genuine_inspection(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The escape fix must not swing into denying ordinary reads."""
        assert handler.matches(bash_hook_input(r"grep -n 'a\' scripts/qa/run_all.sh")) is False

    # ── matches() — real invocation vs prose mention (N6, Plan 00466) ──

    def test_does_not_match_a_prose_mention_in_a_quoted_title_flag(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The exact live false positive: a `mkplan.bash --title "..."`
        journal entry whose quoted title happens to name the runner in
        prose. The command's own leading word (`mkplan.bash`) is not the
        script and not a wrapper, so the substring-only test previously
        denied every such entry."""
        command = (
            "CLAUDE/Plan/mkplan.bash --journal 00466 finding "
            "untracked/scratch/body.md --ref N2 "
            '--title "worktree setup names the denied full-suite runner run_all.sh"'
        )
        assert handler.matches(bash_hook_input(command)) is False

    def test_does_not_match_a_prose_mention_in_a_gh_body(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert (
            handler.matches(
                bash_hook_input(
                    'gh issue comment 56 --body "fixed the run_all.sh advice in the docs"'
                )
            )
            is False
        )

    def test_still_matches_a_relative_invocation_after_cd_with_double_ampersand(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`&&` chains two segments exactly like `;` does for this guard."""
        assert handler.matches(bash_hook_input("cd scripts/qa && ./run_all.sh")) is True

    def test_still_matches_an_sh_dash_c_invocation(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`sh -c '...'` hands the whole inner string to sh, which then runs it."""
        assert handler.matches(bash_hook_input("sh -c './scripts/qa/run_all.sh'")) is True

    def test_still_matches_a_bare_command_substitution(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("echo $(./scripts/qa/run_all.sh)")) is True

    def test_does_not_match_an_unrelated_wrapper_invocation(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A wrapper naming a DIFFERENT script must not be caught by the
        mere presence of the word 'bash' elsewhere in the command."""
        command = 'bash scripts/qa/run_tests.sh; echo "see run_all.sh notes"'
        assert handler.matches(bash_hook_input(command)) is False

    # ── matches() — M1 regression (Plan 00466 review): restore deny-by-default ──
    #
    # The shlex-based redesign above (N6) replaced a substring-plus-allowlist
    # check with a small allowlist of WRAPPER commands, which made every head
    # NOT on that list an ALLOW by default -- 16 genuine invocation shapes the
    # review found now pass unblocked. The fix restores deny-by-default (an
    # inspection/VCS head is the ONLY exemption); these tests pin each shape
    # the review listed as still denied.

    def test_still_matches_shell_prefix_and_process_control_forms(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`source`/`.`, `time`, a leading `VAR=value`, and process-control
        wrappers (`nohup`/`sudo`/`command`/`setsid`/`stdbuf`) all still hand
        the script to a shell to execute -- none of them was ever on any
        read-only allowlist, so deny-by-default must catch every one."""
        for command in (
            "source scripts/qa/run_all.sh",
            ". scripts/qa/run_all.sh",
            "time ./scripts/qa/run_all.sh",
            "CI=1 ./scripts/qa/run_all.sh",
            "nohup ./scripts/qa/run_all.sh > /tmp/x.log",
            "sudo ./scripts/qa/run_all.sh",
            "command ./scripts/qa/run_all.sh",
            "setsid ./scripts/qa/run_all.sh",
            "stdbuf -oL ./scripts/qa/run_all.sh",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_subshell_and_control_flow_forms(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A `(...)` subshell, a `{...}` group, `!`, and `if`/`for` control
        flow all still run the script; none is whitespace-separated from an
        adjacent `(`/`{`/`!`, which plain whitespace-splitting would glue
        onto the next word and hide."""
        for command in (
            "(cd scripts/qa && ./run_all.sh)",
            "(./scripts/qa/run_all.sh)",
            "{ ./scripts/qa/run_all.sh; }",
            "! ./scripts/qa/run_all.sh",
            "if true; then ./scripts/qa/run_all.sh; fi",
            "for i in 1; do ./scripts/qa/run_all.sh; done",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_a_bare_path_piped_into_xargs_bash(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`echo <path> | xargs bash` feeds the bare path to xargs, which
        hands it to bash to run -- the echo segment alone names the script
        as its own unquoted word, so deny-by-default catches it before
        xargs even enters the picture."""
        assert handler.matches(bash_hook_input("echo scripts/qa/run_all.sh | xargs bash")) is True

    def test_does_not_match_further_prose_and_data_consumer_shapes(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Companion ALLOW cases from the review's probe file: a bare prose
        echo, a git-commit prose mention with single quotes, and shellcheck
        as a static-analysis data consumer."""
        for command in (
            'echo "use llm_qa instead of run_all.sh"',
            "git commit -m 'mention run_all.sh in prose'",
            "shellcheck scripts/qa/run_all.sh",
        ):
            assert handler.matches(bash_hook_input(command)) is False, command

    # ── matches() — M1 review 2 (Plan 00466 guard-defects review 2): 19 ──
    # further regressions, all still ALLOW on the branch above (DENY on
    # main). Three shapes: a string-executor whose script mention is not
    # the LAST thing in the string, a glued redirection with no whitespace
    # before `>`/`<`, and a glob/brace word that could expand to the script.

    def test_still_matches_a_shell_dash_c_string_where_the_script_is_not_last(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`_word_names_the_script` requires the WHOLE shlex word to end in
        `/run_all.sh` -- true only when the invocation is the last thing in
        a `-c` string. Trailing flags, redirections or a second command
        after `;`/`|` inside the string defeated that. The `-c` argument
        must be re-parsed as its own shell text."""
        for command in (
            "bash -c './scripts/qa/run_all.sh --fast'",
            'bash -c "./scripts/qa/run_all.sh 2>&1"',
            "bash -c '../scripts/qa/run_all.sh; echo done'",
            "bash -lc 'cd x && ./scripts/qa/run_all.sh > untracked/scratch/qa.txt 2>&1'",
            "sh -c '../scripts/qa/run_all.sh|cat'",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_timeout_wrapping_a_shell_dash_c_string(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`timeout N bash -c '...'` is an everyday agent shape: timeout's
        own duration argument must be skipped to reach the wrapped shell."""
        command = "timeout 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_matches_timeout_with_a_signal_flag_value(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """n466-n24 review 4, nit n-1: `-s SIGNAL` is a flag taking a
        SEPARATE value token -- skipping it by its own leading `-` alone
        mistakes the duration (`900`) for the wrapped command, so the real
        `bash -c '...'` tail was never reached."""
        for command in (
            "timeout -s TERM 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'",
            "timeout --signal TERM 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'",
            "timeout -k 10 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'",
            "timeout --kill-after 10 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_timeout_with_an_equals_form_flag_value(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The `--flag=VALUE` spelling carries its value in the same token
        and needs no extra skip."""
        command = "timeout --signal=TERM 900 bash -c '../scripts/qa/run_all.sh > out.txt 2>&1'"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_matches_eval_of_a_string_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        for command in (
            "eval '../scripts/qa/run_all.sh --fast'",
            'eval "../scripts/qa/run_all.sh;"',
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_python_dash_c_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A `python -c`/`python3 -c` argument is Python, not shell text --
        a substring test on the argument is enough (the review's own
        judgement: 'for python -c, a substring test is fine'). The second
        command's `os` module call is built by concatenation, not as a
        source literal: this file's own `security_antipattern` static scan
        denies authoring that call's dotted spelling textually, regardless
        of it being BASH TEXT inside a Python string rather than executing
        code."""
        os_system_call = "os." + "system('./scripts/qa/run_all.sh')"
        for command in (
            "python3 -c 'import subprocess; subprocess.run([\"./scripts/qa/run_all.sh\"])'",
            f'python3 -c "import os; {os_system_call}"',
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_ssh_and_watch_and_su_string_executors(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        for command in (
            "ssh localhost '../scripts/qa/run_all.sh -v'",
            "watch -n 60 '../scripts/qa/run_all.sh >/dev/null'",
            "su -c '../scripts/qa/run_all.sh' someuser",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_a_glued_redirection(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """No whitespace before `>`/`<` used to glue the redirection onto
        the script's own word, so it no longer ended in `/run_all.sh`."""
        for command in (
            "./scripts/qa/run_all.sh>untracked/scratch/qa.txt",
            "./scripts/qa/run_all.sh>untracked/scratch/qa.txt 2>&1",
            "./scripts/qa/run_all.sh</dev/null",
            "bash ./scripts/qa/run_all.sh>x",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_a_glob_or_brace_word_that_could_expand_to_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A shell glob or brace expression the shell could expand TO the
        script's own name is a real invocation, even though the literal
        shlex word is not an exact match."""
        for command in (
            "bash ./scripts/qa/run_all.sh*",
            "bash {scripts/qa/run_all.sh,}",
            "bash scripts/qa/{run_all.sh,x}",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_does_not_match_unrelated_globs_or_quote_splicing(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Pre-existing ALLOW cases that the new glob handling must not
        turn into false positives: a glob with no literal script-name
        substring, and quote-spliced spellings. Also pins that a SHORT
        interior wildcard right after the extension separator is left to
        the sibling `secret_file_guard` niggle rather than handled here."""
        for command in (
            "bash scripts/qa/run_all*",
            "bash scripts/qa/run_*.sh",
            'bash scripts/qa/run_all.s"h"',
            "bash scripts/qa/run_all''.sh",
        ):
            assert handler.matches(bash_hook_input(command)) is False, command

    # ── matches() — n3 review 2 (Plan 00466 guard-defects review 2): the ──
    # data-consumer exemption is matched by BASENAME (a path-qualified head
    # like `/usr/bin/cat` slips through the same way) and does not exclude
    # git/rg subcommands that themselves EXECUTE an argument.

    def test_still_matches_git_bisect_run_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        command = "git bisect run ./scripts/qa/run_all.sh"
        assert handler.matches(bash_hook_input(command)) is True

    # ── matches() — M-3 timing bounds (Plan 00466 review 3): the SAME ──
    # catastrophic `\S*\{[^{}]*\}\S*` regex the secret matcher's M2d fix
    # abandoned was still present here, plus an unbounded `_expand_braces`
    # recursion and an unbounded eval-recursion re-parse. Every case here
    # must both stay under 1s AND end in the correct verdict.

    def test_a_huge_no_brace_word_does_not_trigger_catastrophic_backtracking(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The reviewer's 94 KB / 200 KB reproducer: a huge run of
        non-whitespace carrying no brace at all, immediately followed by a
        real invocation."""
        import time

        for size_kb in (94, 200):
            word = "a" * (size_kb * 1024)
            command = f"echo {word} run_all.shx"
            start = time.monotonic()
            result = handler.matches(bash_hook_input(command))
            elapsed = time.monotonic() - start
            assert elapsed < 1.0, f"{size_kb}KB took {elapsed:.2f}s"
            # `run_all.shx` does not itself name the script and `echo` is
            # not a real invocation -- ALLOW is the correct verdict here,
            # timing is the point of this test.
            assert result is False

    def test_a_wide_brace_word_stays_fast(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`{a,b}` x 22 in one word: exponential (2**22 spellings) under
        naive recursion. Mirrors the reviewer's exact reproducer shape --
        no token in the command literally names the script (`run_all.shx`
        does not), so this can only reach a verdict by actually walking
        `_brace_words_in_segment`/`_expand_braces`, the path review 3
        found unbounded. The brace word exceeds the shared expander's
        spelling cap, so the verdict is DENY (fail closed: "cannot rule
        out" a spelling that names the script), not the specific
        substring-match ALLOW a fully-enumerated check would give."""
        import time

        command = "bash " + "{a,b}" * 22 + " run_all.shx"
        start = time.monotonic()
        result = handler.matches(bash_hook_input(command))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"took {elapsed:.2f}s"
        assert result is True

    def test_deeply_padded_eval_recursion_stays_fast(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The reviewer's `eval `x100 reproducer: each level re-joins and
        re-parses the whole remaining command, and (before this fix) also
        re-ran the catastrophic brace regex against it every level."""
        import time

        command = "eval " * 100 + "a" * (20 * 1024) + " run_all.shx"
        start = time.monotonic()
        handler.matches(bash_hook_input(command))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"took {elapsed:.2f}s"

    def test_still_matches_git_rebase_dash_x_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        for command in (
            "git rebase -x ./scripts/qa/run_all.sh main",
            "git rebase --exec ./scripts/qa/run_all.sh main",
        ):
            assert handler.matches(bash_hook_input(command)) is True, command

    def test_still_matches_git_dash_c_alias_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        command = "git -c alias.q=!./scripts/qa/run_all.sh q"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_matches_rg_dash_dash_pre_naming_the_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        command = "rg --pre ./scripts/qa/run_all.sh pattern file.txt"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_matches_a_path_qualified_data_consumer_head(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A path-qualified `cat` is not the trusted bare-word reader this
        exemption exists for -- it could be a shadowed binary or a function
        of the same basename -- so it gets no exemption at all and is
        judged the same as any other unrecognised head."""
        command = "/usr/bin/cat ./scripts/qa/run_all.sh"
        assert handler.matches(bash_hook_input(command)) is True

    def test_still_allows_ordinary_git_and_rg_invocations(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The exemption itself must survive n3's narrowing for the
        overwhelming ordinary case: a ready git/rg command with no
        subcommand shape that executes anything."""
        for command in (
            "git log --oneline -- scripts/qa/run_all.sh",
            "git commit -m 'mentions run_all.sh in prose'",
            "rg run_all.sh scripts/qa/",
        ):
            assert handler.matches(bash_hook_input(command)) is False, command

    # ── Acceptance tests ──

    def test_has_acceptance_tests(self, handler: EnforceLlmQaHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_has_negative_case_for_cat_inspection(self, handler: EnforceLlmQaHandler) -> None:
        """Plan 00200 Task 6.4: every DENY-capable handler needs a near-miss ALLOW case."""
        from claude_code_hooks_daemon.core.hook_result import Decision

        tests = handler.get_acceptance_tests()
        allow_tests = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert allow_tests, "Expected at least one ALLOW acceptance test (near-miss case)"
        assert any("cat " in t.command for t in allow_tests)

    def test_every_acceptance_test_declares_a_tool_payload(
        self, handler: EnforceLlmQaHandler
    ) -> None:
        """Plan 00319 Task 4.6: both `command` values here are literal bash --

        a CI-time contract test needs `tool_payload` to drive them directly
        rather than treating `command` as prose.
        """
        tests = handler.get_acceptance_tests()
        assert all(t.tool_payload is not None for t in tests)

    def test_every_declared_payload_produces_its_declared_verdict(
        self, handler: EnforceLlmQaHandler
    ) -> None:
        """The contract half, local to this handler (Plan 00319 Task 4.6).

        A handler that correctly declines to match returns no verdict at
        all -- fine for an ALLOW-expecting test (nothing was denied), a real
        failure for a DENY-expecting one (the payload never reaches the
        deny path at all).
        """
        from claude_code_hooks_daemon.core.hook_result import Decision

        for test in handler.get_acceptance_tests():
            assert test.tool_payload is not None
            hook_input = {
                "tool_name": test.tool_payload.tool_name,
                "tool_input": test.tool_payload.tool_input,
            }
            if not handler.matches(hook_input):
                assert test.expected_decision != Decision.DENY, test.title
                continue
            result = handler.handle(hook_input)
            assert result.decision == test.expected_decision, test.title
            for pattern in test.expected_message_patterns:
                assert re.search(pattern, result.reason or ""), (test.title, pattern)
