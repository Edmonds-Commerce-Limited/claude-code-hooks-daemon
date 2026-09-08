# Task 2.4 — D1 and D7: sensitive_content covers staged content and gh bodies

**Branch**: `agent-a19d365947e1bc2f0-93a59434` (worktree)
**Commits**: `6c9a6f6f` (the fix), plus a follow-up recording that hash in
Plans 00252 and 00264.
**Model**: Fable 5.1

## What changed

Both defects were missing surfaces of the one guard,
`src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py`, so
both are delivered inside it. No new handler, no new rule ID, no new config
option: the existing `R-SENSITIVE-PUBLIC-PATTERN` / `R-SENSITIVE-SECRET-TERM`
rules and their disclosure ladder apply unchanged.

### D1 — staged content at `git commit`

- A `git commit` (token-walked with `git_subcommand_index`, so `git -C x commit` and `/usr/bin/git commit` count) reads
  `git diff --no-color --unified=0 --diff-filter=ACM --cached` in the repo the
  hook's `cwd` resolves to (project root as fallback; no repo means nothing to
  judge). `-a`/`--all`/`-am` switches the diff to `HEAD`, because the index is
  not yet what that commit records.
- Only ADDED lines (`+`, never `+++`) are scanned, attributed per file from
  the `+++ b/<path>` headers. Removing a term is therefore never blocked.
  Binary blobs print no `+` lines and are skipped without a special case.
- The deny names `staged content of <relpath>` plus the pattern name (public)
  or `entry N of M` (secret). The line is never echoed anywhere, and the
  subject is redacted before it reaches the reason exactly as the command
  line already was.
- Bounds, stated in the code and the guidance: `MAX_STAGED_FILE_BYTES` =
  512 KiB of added lines per file, `MAX_STAGED_TOTAL_BYTES` = 4 MiB per
  commit. Past either, the file (or the remainder of the commit) is stood
  down with an INFO log line naming the path only; nothing is scanned
  partially. Handler `exclude_paths`, `daemon.exclude_paths` and the word list
  itself are honoured for staged paths as they are for writes.
- `matches()` and `handle()` share a per-dispatch cache keyed on the
  `hook_input` object, so the diff runs once (asserted by a test that wraps
  `run_git`).

**`git push` is deliberately NOT a surface.** A push carries nothing a commit
did not; a denied commit is never pushed; and judging a push would mean
diffing every ref against the remote, unbounded and racy. The commit is the
gate. Content already in history is the batch scanner's and the history
rewrite's job, as Plan 00252 Decision 2 records.

### D7 — `gh` bodies

- `gh issue|pr comment|create|edit` (anchored at a command start or after a
  separator) makes the whole command a haystack, so an inline `--body`/`-b`
  value is judged like `git commit -m`. `edit` is included because it writes a
  body by the same route; `view`/`list`/`checkout` never match.
- `--body-file <path>` / `--body-file=<path>` / `-F <path>` is read at check
  time (relative to the hook's `cwd`), 64 KiB bound, decode-with-replace, and
  reported as `gh body file <path>` only. A missing/unreadable file or `-`
  (stdin) is skipped: `gh` fails on the former itself, and the latter cannot
  be judged.
- `gh api` is documented as uncovered rather than half-covered: its `-F` means
  a field, and a body there is one generic parameter among many.

## Tests

- `tests/unit/handlers/pre_tool_use/test_sensitive_content.py`:
  `TestStagedContentSurface` (13 tests: deny, path-and-index-only reason,
  public pattern, clean, removal-only, unstaged ignored, `-a`/`-am`/`--all`,
  binary skipped, per-file bound, exclude_paths, no repo, `git push`, single
  diff read) and `TestGhBodySurface` (7 inline shapes, `--body-file` and
  `-F`, relative path against cwd, public pattern, six allowed shapes,
  missing file, stdin). The staged tests write the bytes with no tool call
  and `git add` them, which is the `mv`-then-stage sequence that actually
  failed (Plan 00252 Task 3.3).
- Two acceptance probes added: a secret-list staged-content probe
  (`harness_cannot_produce`, the same boundary as every secret-list probe)
  and a dispatchable public-pattern `gh issue comment --body` deny probe.
- Green: the handler suite (106), `test_staged_lint_gate.py`,
  `test_claude_md_guidance_coverage.py`, the four acceptance-contract suites
  and `test_handler_reference_check.py`. `ruff check`, `ruff format --check`
  and `mypy --strict` clean on the touched Python.

## Docs and plans

- `get_claude_md()`: the "seven places" paragraph is unchanged and still true
  (five metadata surfaces + contents + paths); the paragraph that said "a Bash
  command that writes a FILE is NOT checked" now says the commit is the gate
  for that content, states the bounds, says why `git push` is excluded, and
  adds the `gh` body paragraph.
- `docs/guides/HANDLER_REFERENCE.md` `#### sensitive_content`: a "Four
  surfaces, one guard" list.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-secret-guard-covers-staged-content-and-gh-bodies.md`.
- Plan 00252: Phase 3 (3.1–3.4, with the chosen bounds and the shared
  `term_matches` predicate answering 3.4) and Task 4.3 ticked; Delivery
  carries `6c9a6f6f`. Tasks 4.1/4.2 (full QA, client-mode verification) are
  left for Plan 00362 Phase 3, where the merge-time QA run lives.
- Plan 00264: Question 7 answered in place ("No — it belongs to
  `sensitive_content`"), Delivery carries the hash. Nothing else in 00264
  changes; it stays a size-only plan.

## Not done / for the coordinator

- Daemon not restarted (as instructed). The live daemon runs the old
  handler until the merge's restart.
- No `config-changes` manifest: no option was added or changed; the callout
  is the upgrade-time surface. If the owner wants a manifest entry regardless,
  it is a five-line addition.
- `git commit <pathspec>` (committing named paths without staging) falls to
  the `--cached` diff, so content that is only in the working tree for a
  named path is not judged. `-a` is covered. Recorded here rather than
  guessed at; it is a rarer shape than the `mv`-then-`git add` one that bit.
- Worktree setup: `scripts/setup_worktree.sh` only creates NEW worktrees, so
  the venv was built by calling its SSOT `ensure_venv` against this existing
  worktree (fingerprint-keyed under `untracked/venv-...`) and `uv sync --extra dev` for the test tooling; every python/pytest/ruff/mypy command used that
  venv.
