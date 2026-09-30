# Plan 00466 — adversarial security review 3 of `worktree-n466-guard-defects`

**Reviewer**: Opus 5.5, read-only. I edited no tracked file. Probes are under
`/workspace/untracked/scratch/probe_guards_v3_*` (payloads carry
`"synthetic_source": "review-guards-v3"`), with raw output beside each.
**Branch**: `worktree-n466-guard-defects`, HEAD `27f237d8` (fix commit
`3e3164bd`). Base: `git merge-base main HEAD` = `d14ff619`.
**Scope**: verify review-2 findings B1/M1/M2/m1–m4/n1–n4 are ACTUALLY fixed;
hunt for NEW bypasses the fixes introduced (timing, quoting, substitution,
braces, filesystem, malformed payloads); confirm no new QA exclusions; confirm
tests pin each fix.

## Verdict: NOT READY for merge.

| Severity | Count |
| -------- | ----- |
| Blocker  | 1     |
| Major    | 3     |
| Minor    | 3     |
| Nit      | 2     |

The B1 fix and the two new M2 sub-fixes each REINTRODUCED B1's own class (a
slow scan on a PreToolUse hot path is a fail-open bypass, because a client
socket timeout on the 30 s budget is an ALLOW). One of them — the M2d brace
route — is exploitable from a ~110-byte command and takes a genuine
`cat .vault-password` down with it. That is the blocker.

## What holds up (verified on this branch)

- **M1 is genuinely fixed.** Re-ran the review-2 100-case probe
  (`probe_gd_llmqa.py`) against branch vs main: **0 regressions** (`regressions _vs_main=0`, `probe_guards_v3_llmqa_verdicts.txt`). All 19 shapes review 2
  listed (string-executor `-c`/`eval`/`ssh`/`watch`/`timeout`, glued
  redirections, glob/brace on the path) now DENY on the branch.
- **M2 interior/edge wildcards are closed for a file that EXISTS on disk.**
  The DP-intersection route (M2a/b) denies every interior-`?`/`*` and
  unenumerable-bracket spelling of the start-anchored patterns; the
  filesystem-truth route (M2c) denies interior/edge spellings of the
  both-edges patterns (`*.secret*`, `*vault_pass*`) — I created a decoy file
  matching `*.secret*` and confirmed `cat …/*.se?retkey`, `myapp.se?retkey`
  etc. all DENY, and still deny with a WRONG `cwd` because the route also
  resolves against `project_root` (`probe_guards_v3_fsroot_test.pyprobe`). The
  residual "absent-file spelling ALLOWs" is safe by construction: a glob that
  expands to nothing reads nothing.
- **N11/m1/m2 fail-closed wrappers work for the raise paths the tests cover.**
  `test_secret_file_guard.py` and the review-2 `probe_gd_failclosed.py` both
  confirm an injected raise in `_evaluate`, `handle()`'s tail, `RuleFormatter`,
  `get_data_layer`, an unhashable `transcript_path`, and the scan-deadline
  `TimeoutError` all DENY, including through `HandlerChain.execute(..., strict_mode=False)`. project_containment's equivalent paths (including
  `tool_input=None`, uninitialised root) also DENY.
- **n1/n3 fixed.** The error route echoes only the exception TYPE (verified in
  the deny reason tails). The data-consumer exemption now requires a bare
  trusted head and is voided for `git bisect run`, `git rebase -x`,
  `git -c alias.*=!…`, `rg --pre` (all four DENY on the branch,
  `probe_guards_v3_llmqa_verdicts.txt`).
- **No new QA exclusions or suppressions.** `git diff d14ff619..HEAD` touches
  no `*.yaml`/`*exclusions*`/`*.json` config; the 4 new broad `except Exception` blocks are the N11/m1 fail-closed wrappers — each logs via
  `logger.exception` and DENIES (fail closed), not error hiding.

---

## Blocker

### B1-R3 — the M2d brace-expansion fix is EXPONENTIAL and blows the 30 s budget on a ~110-byte command, taking a real secret mention down with it

- **Where:** `src/claude_code_hooks_daemon/utils/secret_file_matching.py`

  - `:1242-1257` `_expand_braces` — recurses, producing `2**N` spellings for a
    word carrying `N` `{a,b}` groups, with NO cap on the output size.
  - `:1260-1291` `_brace_expanded_tokens` — for each of up to
    `_MAX_BRACE_WORD_MATCHES` (500) brace groups in the command, calls
    `_expand_braces` on that group's whole surrounding non-whitespace word.
    `_MAX_BRACE_WORD_MATCHES` bounds the NUMBER of groups walked, not the
    exponential expansion of any one word.
  - `:1209-1215` `iter_protected_mentions` builds
    `tokens = [*_tokenise(...), *_brace_expanded_tokens(command)]` EAGERLY,
    before the per-token `deadline` loop runs even once. So the 5 s
    `SCAN_DEADLINE_SECONDS` the guard passes is consulted only AFTER the
    exponential list is already materialised — it cannot bound this path.

- **Why it is a bypass, not a slowdown:** identical to the original B1.
  `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`; a
  read-side socket timeout is an ALLOW for the whole PreToolUse chain. So a
  command whose evaluation exceeds ~30 s is allowed to run, INCLUDING any
  genuine protected mention in the same command line.

- **Reproducer** (`probe_guards_v3_brace_bypass.pyprobe` /
  `probe_guards_v3_timing.pyprobe`, run through `secret_file_guard`
  matches()+handle() and through the matcher directly, worktree venv):

  | command (whole line)                 | wall time       |
  | ------------------------------------ | --------------- |
  | `echo {a,b}` × 18                    | 8.0 s           |
  | `echo {a,b}` × 20 (105 bytes)        | 31.3 s          |
  | `echo {a,b}` × 22 (115 bytes)        | > 45 s (killed) |
  | `cat .vault-password; echo {a,b}`×20 | **36.3 s**      |
  | `cat .vault-password; echo {a,b}`×22 | > 90 s (killed) |

  The last two are the exploit: the real `cat .vault-password` mention is in
  the first (tokenise) list and would be found on the first loop iteration —
  but the eager `_brace_expanded_tokens` step builds `2**20`/`2**22` brace
  spellings first, so the matcher takes 36 s / >90 s and the client times out
  and ALLOWS `cat .vault-password` before the daemon ever answers DENY.

- **Why the fix report missed it:** the M2d write-up (fix report, "Own
  findings") says the catastrophic `\S*\{[^{}]*\}\S*` regex was replaced by a
  bounded boundary scan — true, but that only bounds how the WORD is located.
  The `_expand_braces` step that consumes the located word is itself
  unbounded and exponential, and there is no timing test for it (see M-tests
  gap below).

- **Fix direction:**

  1. Cap `_expand_braces` on total spellings produced (a few hundred), and on
     brace-group count PER WORD; past the cap, treat the raw word as a single
     glob token (fail closed) rather than enumerating. `bash` itself caps
     brace expansion; a 110-byte command has no legitimate `2**20` expansion.
  2. Move the `deadline` check so it also bounds token-list CONSTRUCTION, not
     only the per-token loop — or generate the token stream lazily so the
     deadline is reached before the exponential work completes.
  3. Add a timing test with `{a,b}`×N (the pin the current suite lacks).

---

## Major

### M-1 — the M2c filesystem route walks the WHOLE filesystem for a `/**/` token, uninterrupted by the deadline

- **Where:**
  `secret_file_matching.py:1061-1109` `_both_edges_glob_mention` →
  `:1460-1539` `_expand_glob_token`. For an absolute token the search spec is
  `(Path("/"), "**/…")`, and `base.glob("**/…")` walks every directory under
  `/`. `_MAX_BOTH_EDGES_FS_EXPANSIONS` (200) bounds RESULTS examined
  (`examined += 1` per YIELDED match), not directories walked — a glob whose
  final component matches nothing yields nothing, so the counter never trips
  and the whole tree is walked. The `deadline` in `iter_protected_mentions`
  is only checked BETWEEN tokens (`:1213-1215`), so one token's walk runs to
  completion however long it takes.

- **Reproducer** (`probe_guards_v3_timing.pyprobe`, this container):

  - `cat /**/*.se?ret-zq9x; cat .vault-password` — **9.5 s** in one token.
  - `cat **/[a-h][a-h]*.se?ret-zq9x …` (64 bracket forms, project tree) —
    **10.7 s**.
  - 10 × `cat /**/*.se?ret-zq9x` tokens — 9.0 s (deadline caught between
    tokens, but the FIRST token alone already ran multiple seconds).

  On this small container each `/**/` token is ~10 s; on a real client
  filesystem (large home dir, `node_modules`, mounted volumes) a single such
  token can exceed 30 s and fail the whole chain open. `cat /**/…` is not
  caught by `R-ROOT-RECURSION-CATASTROPHIC` (that guards `grep`/`find`/`rg`,
  not `cat`, and here the walk is the SECRET GUARD's own, not a shell command).

- **Fix direction:** bound the filesystem walk itself — cap directories
  visited (not just matches), and/or check the deadline inside
  `_expand_glob_token`'s loop; refuse an absolute token anchored at `/` (or
  any token with a leading `**/`) rather than walking from the root.

### M-2 — `secret_file_guard` fails OPEN when `tool_input` is `None`/`list`/`str`; the m2 caching fix reintroduced the exact hole N11 closed

- **Where:** `secret_file_guard.py:273-283` `_dispatch_key` does
  `tool_input.get(...)` on a value taken as `hook_input.get(TOOL_INPUT, {})`.
  When the payload carries `tool_input: null` (or a list/str), that is not the
  `{}` default (the key exists), so `.get` raises `AttributeError`.
  `_dispatch_key` is called by `_compute_and_cache_matched` (`:297-298`) and
  `_take_cached_matched` (`:310`) OUTSIDE the `_matched_pattern_and_route`
  try/except — so the raise propagates out of `matches()` and the non-strict
  chain (client default) treats it as "did not match" → **ALLOW**.

- **Reproducer** (`probe_guards_v3_toolinput_inner.pyprobe`, and review-2
  `probe_gd_failclosed.py` re-run — `probe_guards_v3_failclosed_out.txt`
  reports `bad=2`):

  ```
  None: matches() RAISED AttributeError at _dispatch_key:277 -> non-strict chain ALLOWS
  list: matches() RAISED AttributeError at _dispatch_key:277 -> non-strict chain ALLOWS
  ```

  The wrapped `_evaluate` DOES correctly log "denying for safety" and return
  the error route — then the unwrapped `_dispatch_key` on the very next line
  raises anyway.

- **This is a regression the fix introduced.** Review 2's own probe recorded
  these two inputs as "either denies (error route) or gives the correct
  verdict" on the pre-fix branch; the m2 `_DispatchKey` bridge (new in
  `3e3164bd`) is what moved a raise back outside the wrapper. It directly
  contradicts the fix's stated guarantee that `matches()`/`handle()` "NEVER
  raise". `project_containment` is unaffected: its `_dispatch_key` uses
  `json.dumps(tool_input, default=str)`, which tolerates `None`/list.

- **Reachability:** the real Claude Code harness always sends a dict
  `tool_input`, so this needs a malformed payload — hence major, not blocker.

- **Fix direction:** normalise `tool_input` to `{}` when it is not a dict in
  `_dispatch_key` (and `_evaluate`), or move the `_dispatch_key` calls inside
  the fail-closed wrapper. Add a chain-level test with `tool_input` `None`,
  `[]`, and a bare string (the current chain tests all monkeypatch a raise,
  so they never exercise this path).

### M-3 — `enforce_llm_qa` still carries the catastrophic `\S*\{…\}\S*` regex the M2d fix removed elsewhere, plus an exponential brace expansion and an `eval`-recursion blow-up

- **Where:** `.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`

  - `:227` `_BRACE_WORD_RE = re.compile(r"\S*\{[^{}]*\}\S*")` — the EXACT regex
    the secret-matcher M2d fix report says it abandoned for being
    "CATASTROPHICALLY slow on adversarial input with no braces at all". It is
    still here, run via `.findall()` at `:232` on every segment.
  - `:210-218` `_expand_braces` — same unbounded `2**N` recursion as the
    secret matcher's (M-blocker above).
  - `:290`/`:404-406` the `eval` string-executor path re-joins and re-parses
    the whole remaining command per recursion level.

- **Reproducer** (`probe_guards_v3_llmqa_timing.pyprobe` — the command must
  contain `run_all.sh` as a substring so `matches()` proceeds, which
  `run_all.shx` satisfies):

  - `echo <94 KB no-space word> run_all.shx` — **15.0 s** (catastrophic
    backtracking of `_BRACE_WORD_RE` looking for a `{` that is not there).
  - `echo <200 KB no-space word> run_all.shx` — **> 45 s (killed)**.
  - `echo {a,b}`×22 ` run_all.shx` — 9.5 s (`_expand_braces` = `2**22`).
  - `eval `×100 `<20 KB pad> run_all.shx` — **> 45 s (killed)**;
    `eval `×80 `<5 KB>` = 4.4 s.

- **Impact:** enforce_llm_qa is priority 41 and its job is to DENY `run_all.sh`.
  A timeout ALLOWS the command — so the guard is bypassed for its own target —
  and it burns the shared 30 s chain budget, which every blocking gate after
  it (staged-lint 43, plan-QA 44, docs-QA 47, guard-config 49) also depends
  on. Not a secret-read route (secret_file_guard at 14 runs first), so major
  rather than blocker.

- **Fix direction:** port the secret matcher's bounded boundary scan +
  capped `_expand_braces` here (same fix, second copy), and cap the `eval`
  recursion depth / re-parse length.

---

## Minor

### m-1 — the timing test suite pins the DP/star shapes but NOT the brace or filesystem shapes that reopened B1

`tests/unit/utils/test_secret_file_matching.py::TestInteriorWildcardDpIsBounded`
covers the 60 KB bracket+star token, 200 bracket+star tokens, 1 MB `a*b`
volume, and a lone 60 000-`*` run — all pass. There is NO timing test for
`{a,b}`×N brace expansion or for a `/**/` filesystem walk, which is precisely
why B1-R3 and M-1 shipped. Add both (the blocker's pin, and a `/**/`-token
bound). Also: `test_the_60kb_bracket_and_star_bypass_shape_denies_fast`
(`:1322`) passes NO deadline, so it exercises only the DP cap, not the
guard's real deadline path.

### m-2 — the both-edges FS route is cwd/existence-dependent (documented, safe, but worth stating)

`_both_edges_glob_mention` only denies an interior-wildcard spelling of a
`*.secret*`/`*vault_pass*` file when that file EXISTS on disk and is reachable
from `project_root` or the threaded `cwd`. When the protected file is absent
(as `.claude/block-words.secret` is in this checkout — confirmed via
`secret-meta`, `exists: false`), every interior/edge spelling ALLOWs. This is
safe (nothing to read) and is the fixer's documented design, but it means the
"interior globs of each shipped protected pattern are denied" acceptance
criterion holds only conditionally for the two both-edges patterns — worth one
honest sentence in the ledger rather than an unqualified claim.

### m-3 — `enforce_llm_qa` deny-by-default over-blocks ordinary read/copy verbs

`ls`, `cp`, `awk`, `vim`, `chmod`, and a bare `echo run_all.sh` now DENY
(`probe_guards_v3_llmqa_verdicts.txt`: main ALLOW, branch DENY, exp ALLOW) —
none executes the script. This is the deliberate, safe-direction cost of the
M1 deny-by-default redesign (over-block, not under-block), so it is a
usability nit rather than a security defect; noting it so it is a known cost,
not a surprise. `stat`/`wc`/`grep` (real inspection heads) stay ALLOW.

## Nit

### n-1 — `_strip_timeout_prefix` mis-skips a flag VALUE

`enforce_llm_qa.py:318-335` skips `timeout`'s flags by leading `-` but not
their values (`timeout -s SIGKILL 9 bash -c '…run_all.sh'` would mistake `9`
for the command). The docstring acknowledges this and argues it fails toward
"no match" (allow), which for THIS guard is the safe-usability direction; low
value, but the acknowledged gap is a real (tiny) detection hole.

### n-2 — `_dispatch_key` (project_containment) repr fallback path is untested

`project_containment.py:86-101` falls back to `repr(tool_input)` when
`json.dumps` raises `TypeError`. Correct and logged, but I found no test
exercising a non-JSON-serialisable `tool_input` with an unsortable key; add
one so the fallback is pinned.

---

## Cross-cutting note (context for the ledger, not a new finding)

Review 2's B1 fix, and both new M2 sub-fixes, each independently reintroduced
B1's own defect class — a slow SAFETY-guard scan is a fail-open. That is three
instances of the same class in one fix commit, all missed because the pinning
was per-shape (the exact strings review 2 measured) rather than a structural
bound. The durable fix is a single whole-scan wall-clock deadline that also
covers token-list CONSTRUCTION and the filesystem walk, plus caps on any
expansion (brace, bracket, glob) BEFORE the work is done — not another
per-shape timing test. This is the same "a slow handler is a bypass" class the
review-2 m3/N25 destructive_git work already owns on main; B1-R3 and M-1
should be recorded as belonging to it.

## Probe index (all under `/workspace/untracked/scratch/`)

- `probe_guards_v3_common.pyprobe` — shared helpers (protected names assembled
  from reversed strings; each guard run in a fresh worktree-venv interpreter,
  hard-capped).
- `probe_guards_v3_timing.pyprobe` / `_out.txt` — B1 re-run + brace/`/**/`/DP
  shapes at 32/94/200 KB.
- `probe_guards_v3_brace_bypass.pyprobe` — the `cat .vault-password; echo {a,b}×N` secret-read exploit timing.
- `probe_guards_v3_llmqa_timing.pyprobe` / `_out.txt` — enforce_llm_qa regex /
  brace / eval-recursion cost.
- `probe_guards_v3_llmqa_verdicts.txt` — review-2 100-case branch-vs-main
  verdict diff (0 regressions).
- `probe_guards_v3_secret_verdicts.txt` — review-2 secret probe re-run.
- `probe_guards_v3_fsroot_test.pyprobe` — decoy-file proof the M2c FS route
  denies interior wildcards when the file exists.
- `probe_guards_v3_bothedges.pyprobe` — both-edges route with cwd threaded.
- `probe_guards_v3_toolinput_inner.pyprobe` + `probe_guards_v3_failclosed_out.txt`
  — the `tool_input` None/list fail-open.
- `probe_guards_v3_pytest.txt` — `TestInteriorWildcardDpIsBounded` +
  `test_secret_file_guard.py` (96 passed).

No real protected file was opened; `.claude/block-words.secret` was never read.
Every protected name in the probes is judged as text only, and the one decoy
file created (a zero-byte `*.secret*`-matching name under
`untracked/scratch/`) was removed after use.
