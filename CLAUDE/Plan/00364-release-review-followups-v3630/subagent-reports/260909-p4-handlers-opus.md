# Plan 00364 Phase 4 — handlers residue (review-handlers suggestions 1 and 3)

**Worktree**: `worktree-plan-00364-p4-handlers`
**Scope**: Tasks 4.1 and 4.2 only. Handlers suggestion 2 (`tdd_enforcement`
`Path.cwd()` anchoring) is a declared Non-Goal and was not touched.

## Task 4.1 — the staged-content bounds now cap the peak

### What the finding was

`MAX_STAGED_FILE_BYTES` / `MAX_STAGED_TOTAL_BYTES` were applied per entry of an
already-built map. `run_git` returned the WHOLE staged patch and
`_added_lines_by_path` then built a full copy of its added lines, after which
the bounds decided what to look at. The constants bounded the SCAN, not the
peak their own comment claims to bound: a commit staging a large generated
artefact pulled all of it into the daemon and only then stood it down.

### What it does now

Two questions, cheapest first.

1. `git diff --no-color --numstat -z --diff-filter=ACM <target>` returns one
   added-line count per path and no content whatever. Everything decidable
   without content is decided here: a binary blob (`-` counts), a path with no
   added lines, an excluded path, the secret list itself, a file the per-file
   bound already excludes, and everything past the whole-commit budget.
2. `git diff --literal-pathspecs --no-color --unified=0 --diff-filter=ACM <target> -- <surviving paths>` fetches only what will actually be scanned.
   The exact byte bounds are then applied to the real text, exactly as before.

Peak memory is now the added lines of the paths that survive selection. git is
never asked for a binary blob, an excluded path, an oversized path, or anything
past the budget — which is the substance of the finding.

### The one thing it does not bound, stated plainly

`--numstat` counts LINES; the constants are BYTES. An added line costs at least
the newline that ends it, so a line count is a sound LOWER bound on bytes: a
file whose line count alone passes the byte bound cannot possibly fit, and is
dropped unread. The converse does not hold. A file with few but very long lines
(a minified bundle on one line) passes the sizing pass and is still fetched
before the exact byte count rejects it. git offers no per-path byte figure in a
diff, so closing that gap would need a second object-size query
(`--raw -z` plus `cat-file --batch-check`, which needs stdin support in
`run_git`). Not done, and not needed for the case the finding was about.

### Behaviour preserved

- Both stand-down log lines keep their wording. Each file is logged at most
  once: a file dropped by the sizing pass never reaches the exact check.
- The whole-commit stand-down fires ONCE and names the first path left
  unjudged, whether the sizing pass or the exact byte count stopped the walk.
  `_StagedSelection.stood_down_at` carries the sizing pass's stop point into
  the scan so the two cannot each log a different file for one truncation.
- Rename detection is untouched (`--diff-filter=ACM` still drops `R`). The
  pathspec restriction can make git report an unpaired rename destination as an
  ordinary addition, so each fetched path is checked against the selection.
- `--literal-pathspecs` keeps a file genuinely named `*.log` or `:(icase)x`
  from being read as pathspec magic.

### Two deliberate additions

- **Pathspec chunking** (`_MAX_PATHSPEC_ARGV_BYTES`, 64 KiB). A commit staging
  thousands of files would otherwise build an argv past `ARG_MAX`; `run_git`
  reports the resulting `OSError` as a non-zero return code, which this handler
  reads as "no staged diff". Without chunking the change would stand the guard
  down silently on exactly the large commit it most needs to judge.
- **Unrestricted fallback for a name that cannot round-trip.** `run_git`
  decodes with `errors="replace"`, so a path carrying a byte that is not valid
  UTF-8 comes back bearing U+FFFD and would match no pathspec. Rather than let
  such a file go unscanned, that commit asks the unrestricted question and
  every staged path is judged — the peak returns to what it was, for that
  commit only. Narrowing is an optimisation; the guard is not.

### Tests

New `TestStagedContentIsBoundedBeforeItIsRead` and `TestNumstatParsing` in
`tests/unit/handlers/pre_tool_use/test_sensitive_content.py`, plus a `_GitSpy`
helper that records each invocation's argv AND how many bytes of stdout it
pulled in — `call_args_list` alone cannot answer whether content entered the
process.

The headline test runs against the REAL constant: it stages a file of
`MAX_STAGED_FILE_BYTES + 2` added lines beside a small file carrying a term,
then asserts the oversized path appears in no pathspec, the small one does, the
term is still caught, and total git stdout across the dispatch is smaller than
the oversized file. Also covered: sizing-before-content ordering, the per-file
stand-down log, an excluded path never fetched, a binary blob never fetched,
the commit bound stopping the fetch and logging once naming `b.txt`, chunking
producing more than one content call, and the undecodable-name fallback. The
numstat parser is pinned on the normal record, an unquoted non-ASCII path, the
binary `-` form, the two-path rename form, and empty input.

Two existing tests asserted "exactly one `diff` call per dispatch" as the proof
that `matches()` and `handle()` share one read. One dispatch now asks two
questions, so both assert one sizing call and one content call instead. The
property under test is unchanged.

## Task 4.2 — `refreshInterval: 1` is already in the release notes

No callout added. The recommendation is stated in three places already:

- `RELEASES/v3.63.0.md:81` — "The session-start suggestion now recommends
  `refreshInterval: 1`, the value the daemon has shipped since Plan 00175".
- `CHANGELOG.md:186` — same, and adds the installer's no-venv fallback.
- `CLAUDE/UPGRADES/v3/v3.62.1-to-v3.63.0/release-notes/22-statusline-interval-temp-names-and-bug-report-tool.md`
  — the audience-facing callout, which also tells a project that copied the old
  `10` what it gets by lowering it.

The reviewer read the change as a tenfold increase every client is advised to
adopt. The notes frame it as the SUGGESTION catching up with a default the
daemon itself has shipped since Plan 00175; `RELEASES/v3.44.0.md` announced
lowering that default from 10 to 1, with the ~39 ms cached render as the
argument. So the user-visible fact and its rationale are both already
published, and a fourth statement would be duplication.

## Notes for the coordinator

- **Cost**: every `git commit` dispatch now spawns two git processes instead of
  one. The numstat call is cheap (no content), and it saves fetching content
  the handler was going to discard. A commit with no staged additions now
  spawns ONE process and fetches nothing, where it previously fetched the whole
  diff.
- **The worktree could not run `llm_qa.py` as delivered.** `scripts/qa/llm_qa.py:30`
  hardcodes `untracked/venv/bin/python`, while the canonical resolver
  (`scripts/lib/resolve_venv.sh`) looks for `untracked/venv-*`. The main
  checkout only works because `untracked/venv` happens to be a symlink to its
  fingerprint venv. I reproduced that shape here: populated this worktree's own
  fingerprint venv with `UV_PROJECT_ENVIRONMENT=... uv sync --frozen --all-extras` and symlinked `untracked/venv` to it. Both are gitignored and
  point at the WORKTREE's venv, not the main checkout's. Worth filing:
  `llm_qa.py` should use the resolver rather than the legacy path that
  `venv-include.bash:113` refuses to create.

## QA result: 22/26, and why the four are not reachable from this phase

`./scripts/qa/llm_qa.py all` reports **22/26 passed, 4/26 failed**. Every green
gate that judges this change is green: `format`, `lint`, `type_check`,
`magic_values`, `eacces_safe`, `semgrep`, `security`, `sensitive_content`,
`doc_truth`, `handler_reference`, `british_english`, `project_handlers`,
`hook_contract`, `input_contract`. The four failures have two root causes,
both reproduced directly, and neither is code this phase touches — the only
modified source files are `sensitive_content.py` and its test.

**Cause A — every absolute path in this worktree contains `untracked/`.** The
worktree lives at `/workspace/untracked/worktrees/…`, and both audits exclude
by SUBSTRING against the absolute path
(`audit_error_hiding._DEFAULT_EXCLUDE_PATTERNS` contains `untracked/`). The
whole tree is therefore skipped. Reproduced:
`_collect_shell_files(DEFAULT_SCAN_DIRS)` returns 0, and the error-hiding scan
finds 0 findings, which is why all 172 reported violations are
`stale-exclusion` — every entry in the exclusions file matches nothing. This
hits `error_hiding`, `capture_corruption`, and the two unit tests
`test_audit_capture_corruption.py::TestRealRepoIsClean::test_default_scan_dirs_clean`
and
`test_audit_error_hiding.py::TestStaleExclusionsAreReported::test_the_live_exclusions_file_has_no_stale_entries`.
It affects all four Plan 00364 phase worktrees equally.

**Cause B — the worktree has no `.claude/hooks-daemon.env`.** That file is
gitignored, so a fresh worktree does not get it, and `.claude/init.sh:207`
only enters self-install mode when it is present. Without it
`HOOKS_DAEMON_ROOT_DIR` defaults to `.claude/hooks-daemon`, the wrappers look
for `.claude/hooks-daemon/scripts/lib/resolve_venv.sh` that a self-install
checkout never deploys, and every wrapper call returns its
`"Hooks daemon not installed - protection not active"` fallback. Reproduced by
running `.claude/hooks/stop` by hand. This hits `smoke_test`, the two
`test_forwarder_socket_stdin.py` cases, and
`tests/acceptance/test_tool_use_error_recovery.py`.

Note the fallback is `decision: block`, so the `stop_no_explanation` probe
"passes" for the wrong reason — the smoke gate is vacuous in a worktree, not
merely failing.

I started this worktree's own daemon (`./bin/hooks-daemon restart`, socket
`untracked/daemon-d9e1d4029747.sock`) to rule the daemon out; it made no
difference, because the wrappers never reach it. **I deliberately did not
create `.claude/hooks-daemon.env`.** Cause B is Task 5.1's subject matter, and
a local override would mask the defect that task exists to reproduce. It would
not have reached 26/26 either, since Cause A needs an audit-script change that
is outside this phase and would collide with the other phases.
