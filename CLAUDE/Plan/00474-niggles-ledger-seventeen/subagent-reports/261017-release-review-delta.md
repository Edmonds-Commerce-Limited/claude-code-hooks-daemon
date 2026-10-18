STOPPING BECAUSE: the delta review is finished. Four defects are confirmed: two are false-positive DENYs that the review fixes introduced, one is an incomplete fail-open fix, and one is a crash in Plan 00531.

# Release Step 10 delta review: 9513c3d45..9d1a522b0, `src/` plus the tests added with it

## Scope covered
I read the whole diff for all 20 files under `src/` and the matching test diffs. I checked the risky parts with probe runs on `untracked/venv-workspace-py311-2a519198/bin/python`:
- `message_files.message_file_writers` and `sensitive_content._metadata_commands`
- `simple_commands._spelled` / `_in_double_quotes`
- `core/utils._git_directory` / `_under_directory`
- `yaml_loading._DEEP_LINE_PREFIX`
- `remote_docs` fetchers (named session) and store (retry, `on_failure`)
- `daemon/paths._holds_no_user_memory`
- `stale_litter`
- the comment extractor and `comment_size` / `comment_changelog` fragment mode
- `rust_strategy.is_tool_unavailable_output`
- `github_auto_close_keywords`
- Plan 00531: the `plan_fact_check` resolve/tuning code, `plan_fact_check_feed`, `agent_assets` (derived-from marker, `stale_derived_agents`), `deployed_artefact_drift`, and the agent template. `unpinned_agents()` returns `[]`.

## DEFECTS (4: all CONFIRMED)

**D1. N474 fix makes valid serde/thiserror crate modules fail lint (false-positive DENY).** CONFIRMED with real rustc.
- Location: `src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py:206-213`
- Failing input: a crate module containing `use serde::Serialize; #[derive(Serialize)] #[serde(rename_all="camelCase")] pub struct A { #[serde(default)] a: u8 }`.
- rustc reports `error[E0432]: unresolved import serde`, then an uncoded `error: cannot find attribute 'serde' in this scope` for each helper attribute. thiserror's `#[error("..")]` does the same.
- The new rule allows only when every error line is crate-context, so `is_tool_unavailable_output` now returns False. Before the fix this was ALLOW.
- Derive helper attributes are ordinary Rust, so this hits a large share of real Cargo modules.
- Why tests miss it: no test pairs an unresolved derive crate with its helper attributes.
- Fix: treat `error: cannot find (attribute|derive macro|macro) ...` as crate-context when an E0432/E0433 is present, or classify by excluding known cascades rather than requiring `all`.
- Evidence: `untracked/scratch/rv-rust/serde_helper.rs` and `out.txt`.

**D2. N475 fix denies ordinary code edits as oversized comments.** CONFIRMED.
- Location: `src/claude_code_hooks_daemon/strategies/comments/extractor.py:235-242`, used by `comment_size` and `comment_changelog` for every Edit.
- Fragment mode reads any unterminated `/*` as a comment running to the end of the fragment, including one inside a string.
- Failing input: an Edit on `.ts`, `.go` or `.rs` whose `new_string` is `const files = glob("dist/*.js");` followed by 45 lines of code, with `old_string` being those 45 lines. `comment_size` returns matches=True and handle=DENY.
- `Accept: "*/*"` and globs like `"src/*.rs"` are everyday strings. The whole-file rule existed to stop exactly this (#75).
- Why tests miss it: the fragment tests only use a real `/*` opener at the start of a line.
- Fix: in fragment mode, count an unterminated opener only when nothing but whitespace precedes it on its line (or it follows a line that opens a comment).

**D3. N473 fix is incomplete: a message file built through a pipe or a `{ }` group is still not judged (fail-open).** CONFIRMED by calling `_metadata_commands` directly.
- Location: `src/claude_code_hooks_daemon/utils/message_files.py:113-140`
- `message_file_writers` keeps only the segment whose write target is the named file. Splitting on `|` and `;` drops the segment that actually produces the text. All of these return no haystack with the term:
  - `echo "TERMX" | tee msg.txt && git commit -F msg.txt`
  - `{ echo TERMX; } > m.txt && git commit -F m.txt`
  - `echo TERMX | git commit -F -` (stdin)
- Same-family gap: the stdin case `echo TERMX | git commit -F -` came in with the per-command split, before this range. The `STDIN_MESSAGE_FILE` comment ("the command text, which every caller scans anyway") is no longer true for `sensitive_content`.
- The same gap applies to `github_auto_close_keywords.py:351`.
- Why tests miss it: the parametrised cases use only `>` redirects and heredocs.
- Fix: keep the whole pipeline (stages joined by `|`) and any `{ }` / `( )` group that contains a writer. For `-F -` with no heredoc, keep the pipeline that feeds the recording command.

**D4. Plan 00531: `stale_derived_agents` crashes the session-start drift report on a dangling symlink or a `*.md` directory.** CONFIRMED.
- Location: `src/claude_code_hooks_daemon/install/agent_assets.py:405`
- It calls `path.read_text` on every `.claude/agents/*.md` with no `is_file` check and no OSError handling. It raises `IsADirectoryError` or `FileNotFoundError`, so `DeployedArtefactDriftHandler.handle` raises and the whole drift advisory is lost, agents/docs/plan tooling included. This is a project-owned directory the daemon does not control.
- Why tests miss it: no test covers a directory or dangling symlink.
- Fix: skip anything that is not a file, and use `read_text_or_reason` or `log_and_continue` on OSError.
- Evidence: `untracked/scratch/rv531` and `untracked/scratch/rv531b`.

## NON-DEFECTS
- **`core/utils.py:1137`, N484 residue (low; arguably outside the threat model).** `git -c k=v -C sub rm f` yields no targets, so it is a fail-open in `write_protected_paths`. `_is_command_word` filters `k=v` as a shell assignment, so `-c` swallows `-C` and `sub` ends the scan. This predates the delta, and `git -c k=v rm f` alone works. I'd still file it.
- **`plan_fact_check.resolve_checker_agent`:** a non-string `tuned_agent`, such as a number, raises TypeError in `fullmatch`. A misconfigured `tuned_agent` logs a WARNING on every PostToolUse event.
- **`deployed_artefact_drift`:** the header calls everything "a daemon-owned file", but tuned copies are project-owned, so the wording is wrong for them.
- **The other fixes are correct and I found no fail-open:**
  - loop unrolling handles quoted, glob, single-quoted and `${f}` cases
  - `_git_directory` handles chained `-C`, `--work-tree`, `--git-dir`, wrappers and `-t`
  - the yaml line-prefix bound is right
  - `/proc` stat field 6 is the flags field
  - the `stale_litter` deadline still marks itself exhausted via `expired()`
  - the remote_docs retry path is sound
  - `deliver_pending` reads `offered_due` lazily, which fixes the N486 double hand-over
- I checked both the template md5 and the historic-version ledger.

## Not reviewed
- Whether agent-browser accepts `--session` after the `read`/`close` subcommand. Its help lists `--session` as a global option, but I did not launch a browser to check the placement.
- The `tests/integration/test_acceptance_contract.py` (N493) harness, beyond its diff.
- `daemon/cli.py`, beyond printing the `on_failure` causes.

The full test suite was not run. Probe files are in `/workspace/untracked/scratch/rv-rust/`, `/workspace/untracked/scratch/rv531/` and `/workspace/untracked/scratch/rv531b/`.