# v3.70.0 Step 10 code review: src/claude_code_hooks_daemon/utils/

Scope: `git diff v3.69.0..HEAD -- src/claude_code_hooks_daemon/utils/` (HEAD 9513c3d45), 65 files, +6832/-330.
Reviewer: rel-review-utils (read-only). Probe scripts kept in /workspace/untracked/scratch/rel-review-utils/.

## Scope covered (files read)

Read in full (diff plus the surrounding code needed to trace the paths):
- simple_commands.py (new, 461 lines): all of it, plus how write_protected_paths.py consumes it (`_spelled_violation`, `_command_violation`, `_verbs_violation`)
- shell_segmentation.py: every hunk (git `-c` command-key screen, `-b/--body` gh blanking, the `while read ... done <<'EOF'` loop exemption, `gh` heredoc sink, `_Nesting` / `comments_end_at_newline`)
- command_position.py: every hunk (comment-aware segment spans, `without_comment`, git/awk literal blanking, sudo elevation of `-c` bodies)
- command_evasion.py: every hunk (`QUOTED_SPAN_REGEX`, the quoted-word git global option regex, `git_grep_word_roles`)
- git_commit_parsing.py: every hunk (staging runs for update-index/apply, `_walk` group/pipeline/case/function directory tracking); probed with 14 directory-tracking shapes, all placed the commit where bash would or marked it uncertain
- staging_simulation.py: every hunk (update-index / apply simulation)
- secret_file_matching.py: every hunk (find -regex text operands, `_may_change_directory` prefilter, git grep roles)
- find_expression.py, gh_view_comments.py, full_qa_exemption.py, repository_scope.py, merge_scope.py, git_invocation_directory.py, git_repo.py (hunks), usage_pause_gate.py (hunks), shell_expansion.py (hunk)
- sweep_cache.py, transcript_tail.py, transcript_spend.py (full)

## DEFECTS

### D1. A `for` loop over a quoted `"$var..."` operand hides every word after the first from write_protected_paths (fail-open). CONFIRMED (reproduced)

Location: `src/claude_code_hooks_daemon/utils/simple_commands.py:426-432` (`_unrolled`), consumed by `handlers/pre_tool_use/write_protected_paths.py:777-780`.

`_unrolled` substitutes the loop variable with the regex `"?\$(?:\{VAR\}|VAR(?![A-Za-z0-9_]))"?`. The optional quotes are consumed on either side independently. So when the variable sits inside a quoted word with more text after it (`"$f.local"`, `"$d/ccy.env.local"`, `"${d}/x"`), the regex eats the OPENING quote but leaves the closing one. Each unrolled copy then has one unbalanced `"`. The copies are joined with `"; "`, so the first copy's stray quote opens a string that swallows the `;` and the next copy. `simple_commands` then reads ONE `rm` whose single operand is `a.local; rm .claude/ccy/ccy.env.local`, and the second `rm` and its protected operand are never judged.

Reproduction (probe_loops.py, real handler, configured path `.claude/ccy/ccy.env.local`):

    for f in a .claude/ccy/ccy.env; do rm "$f.local"; done        -> UNROLLED: rm a.local"; rm .claude/ccy/ccy.env.local"   -> ALLOW
    for d in a .claude/ccy; do rm "$d/ccy.env.local"; done          -> ALLOW
    for d in a .claude/ccy; do rm "${d}/ccy.env.local"; done        -> ALLOW
    for d in .claude/ccy; do rm "$d/ccy.env.local"; done            -> DENY (single word: caught by the text fallback)
    for d in a .claude/ccy; do rm $d/ccy.env.local; done            -> DENY (unquoted: correct)

`rm "$d/file"` is the ordinary, careful way to quote a path in a loop, so this is in scope for the careless-agent threat model. It is not a hostile shape.

Why the suite misses it: the loop cases in `tests/unit/handlers/pre_tool_use/test_write_protected_paths.py:910-936` quote only the bare variable (`"$f"`, where the regex eats both quotes) or leave it unquoted (`$f`, `${f}`). None has text after the variable inside the quotes. The one multi-word protected case (`'for f in /tmp/a {p}; do rm "$f"; done'`) uses a bare `"$f"`.

Fix: substitute the variable inside the word rather than removing its quotes. Replace only `\$VAR` / `\$\{VAR\}` with the word, shell-quoted (for example `shlex.quote(word)` dropped into an unquoted context, or the raw word inside existing double quotes), and leave the surrounding quote characters alone. Add a regression row for each shape above.

DEFECTS: 1 (1 confirmed, 0 plausible).

## NON-DEFECTS

N1. `shell_segmentation.py:401-446` `_is_inert_config_setting` is a DENY-list of command-running git config keys. A `git -c <key>=...` with any key it does not list is treated as inert and allows the heredoc exemption. The current list covers every key I could name that `commit`/`merge`/`tag`/`notes`/`apply` would run, so I found no reachable gap. But git keeps adding command keys (`hook.<name>.command` is only covered by the `.command` suffix by luck). Suggestion: allowlist the plain-value keys agents actually set (`user.*`, `core.autocrlf`, `commit.gpgsign`, `color.*`, ...) and treat everything else as able to run. Severity: suggestion.

N2. `_loop_only_prints_its_input` (`shell_segmentation.py:1652-1702`) lists `let`, `test` and `[` as data commands. Bash arithmetic evaluates `a[$(cmd)]` subscripts, so `while read l; do let "$l"; done <<'EOF'` can run body text. This is a hostile shape and outside the threat model, so it is not a finding. If it is ever tightened, dropping `let` costs nothing.

N3. DRY drift between the shell readers:
- `simple_commands.SHELL_INTERPRETERS` (adds `ash`, `rbash`) differs from `command_position.SHELL_NAMES` (no `ash`/`rbash`).
- `simple_commands._is_command_flag` duplicates `command_position.is_shell_command_option`.
- `command_position._AWK_RUNNABLE_MARKERS` (`system`, `|`) differs from `secret_file_matching._AWK_RUNNING_MARKERS` (`system`, `getline`, `|`).

All three are the same concept kept in separate places. Fix: one constant and one helper in a leaf module. Severity: important (DRY).

N4. `git_commit_parsing._staging_runs` (`git_commit_parsing.py:828-829`) marks a staging run stdin-fed only when its operator is exactly `|`. `cmd |& git update-index --index-info && git commit ...` is read as not fed, so its entries "stage nothing" in the simulation. This is exotic. Fix: test `step.operator in _PIPE_OPERATORS`. Severity: suggestion.

N5. `gh_view_comments._asks_for_comments` (`gh_view_comments.py:52`) splits `--json` fields on `,` without stripping, so `--json "title, comments"` is denied as uncommented (a false positive, which is the safe direction). Fix: `[f.strip() for f in fields.split(",")]`.

N6. `sweep_cache._read_cache` (`sweep_cache.py:291-305`): a cache file that is not valid JSON logs twice (the `log_and_continue`, then "not an object"). Cosmetic: return None right after the swallow.

N7. `sweep_cache._work`: two concurrent fingerprints for the same sweep can finish out of order, so the older result overwrites the newer cache file. That is never served as current (fingerprint mismatch means a recompute), so it costs one extra recompute. No action needed beyond awareness.

N8. `transcript_spend._apply`: `seen_ids` grows without bound and is persisted in full on every save. Memory and sidecar size grow with request count per agent. Acceptable at current sizes; worth a cap if very long-lived agents appear.

## Not reviewed (honest)

Context budget ran out before I got to these new or changed modules. They are NOT reviewed and need a follow-up pass:
- session_thread_group.py (+514), spend_ledger.py (+323), plan_fact_check.py (+322/-), workflow_fanout.py (+319), dispatch_tier.py (+312), stale_litter.py (+258), session_load.py (+224), workable_issues.py (+156), agent_dispatch_registry.py (+149, feeds the full-QA exemption's agent-type resolution, so it is the highest priority of these), model_tiers.py (+76), operator_signal.py (+105), goal_ledger.py, deliberate_swallow.py, fake_values.py, deployed_version.py, markdown_format.py, retention.py, ccy_supervisor.py, container_detection.py, subagent_report_paths.py, stop_hook_helpers.py, usage_pause.py, and the small (<25 line) hunks in the remaining files (mostly `logger.debug` -> `log_and_continue` swaps, judging by the stat).
- In git_commit_parsing.py, the `_walk` group/pipeline state machine was probed on 14 shapes rather than proved. I did not test nested functions inside pipelines or `select`.
- I did not check test coverage per behaviour beyond the write_protected_paths loop rows cited in D1.
