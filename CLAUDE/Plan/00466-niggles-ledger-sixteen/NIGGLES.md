# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N35 — In Progress — adversarial security review of the N24/N25/N34 fix (2 blockers, 3 majors, 6 minors, 4 nits)

**Found by an adversarial, read-only security review**
(`subagent-reports/260924-n466-n24-review-opus-5-5.md`) of `d7f2c875` (N24 +
N25 + N34 combined). Verdict: NOT READY — inputs existed that turned a
SAFETY+BLOCKING decision into ALLOW. Full report committed at `f8f2dfeb`.
Findings and remediation status, in the report's own order:

**B1 (blocker) — ✅ Remedied.** A lone UTF-16 surrogate anywhere in
`tool_input` crashed `_safety_payload_size` (`chain.py`, strict
`.encode("utf-8")`) OUTSIDE every handler's own try/except; the crash
propagated to `controller.py`'s catch-all, which built an ALLOW (no
decision) via the pre-existing, deliberately-fail-open `HookResult.error()`.
Reproduced live: `git reset --hard HEAD # \ud800` allowed on this branch,
denied on base `3104434b`; fail-open was new here, not pre-existing.

Fixed in three layers: (1) `_safety_payload_size` rewritten to serialise the
WHOLE `tool_input` via `json.dumps(..., ensure_ascii=False)` then
`.encode("utf-8", "surrogatepass")`, wrapped in try/except returning 0 on
`TypeError`/`ValueError` — this also happens to satisfy the report's m5
finding (the old 4-field summation missed `file_path`/MultiEdit's `edits[]`/
NotebookEdit's `new_source`) as a side effect, since the whole dict is now
measured regardless of shape; (2) the measurement call site in
`HandlerChain.execute` is now itself wrapped: any exception computing it
denies immediately, chain-level, when the chain holds a SAFETY+BLOCKING
handler (nothing to protect ⇒ degrades to an unmeasured/uncapped chain
instead, never a regression); (3) new `HookResult.error_deny()` factory
(fail-closed counterpart to the pre-existing `error()`, reason names the
error, context gives `bin/hooks-daemon status`/`restart` recovery
instructions) — `DaemonController.process_event`'s and `process_request`'s
catch-all exception handlers now use it, but ONLY when the event is
`PreToolUse`; every other event type keeps the pre-existing fail-open
`error()` deliberately, per the review's own scoping. RED tests: a lone
surrogate in each of `command`/`content`/`new_string`/`old_string` denies
via the guard's own reason, not a crash
(`tests/unit/core/test_chain.py`); a forced size-measurement crash denies
chain-level when a SAFETY+BLOCKING handler exists and degrades gracefully
when none does; `controller.py`'s router-exception and pre-validation
catch-alls deny for `PreToolUse` and still fail open for every other event
(`tests/unit/daemon/test_controller.py`, 4 new cases plus one pre-existing
case's assertion flipped from ALLOW to DENY — a deliberate behaviour change,
not a mistake). These tests exercise `chain.execute`/
`controller.process_event`/`process_request` directly rather than the
report's own real-socket reproducer; a real-socket integration test for
this specific surrogate shape is not yet added (tracked below).

**B2 (blocker) — ✅ Remedied.** `path_exclusion.py`'s `path_matches_globs`
translated a client's exclude glob into a regex (`_glob_to_regex`) and
matched it via `compiled.fullmatch(candidate)`. Against a `file_path` built
from many short segments (`"a/" * n`) the backtracking regex engine went
quadratic-or-worse AND held the GIL for the ENTIRE call: N34's
`BoundedDispatcher` waits on `Future.result(timeout=remaining)` from a
DIFFERENT thread, but nothing can run on that thread while the C-level `re`
call holds the GIL, so the timed wait cannot even observe, let alone
interrupt, the hang — N34's own core claim defeated by its own root cause.
Reproduced live: `probe_n24r_p9_pathhang.py` measured 1.9s at 4000 segments
(unbounded growth from there); `probe_n24r_p11_gil.py` over the real socket
showed a single adversarial Write freezing concurrent PreToolUse calls until
the CLIENT's 30s timeout (fail-open); `hooks-daemon stop` returned in ~6s
but the daemon was still alive at 99% CPU (Python signal handlers only run
between bytecodes) and needed SIGKILL.

Replaced the regex translator with a hand-written linear matcher
(`_tokenize_glob` + `_apply_prefix`/`_apply_literal`/`_apply_qmark`/
`_apply_star`/`_apply_segstar`/`_glob_fullmatch`): each pattern tokenizes
once (cached, as before) into `PREFIX`/`LITSTR`/`QMARK`/`STAR`/`SEGSTAR`/
`ANYALL`, and matching is a left-to-right sweep over a boolean "reachable
position" array per token — no backtracking is possible by construction.
`SEGSTAR` (mid-pattern `**/`) needed care: an earlier, simpler design that
treated it like a plain `.*` was caught by hand-tracing `**/secret` against
`xsecret` — that shortcut would have matched (treating "x" as an admissible
empty prefix) where the original regex correctly does not, since `**/`
requires a COMPLETE, non-empty path segment. The shipped `SEGSTAR`
implementation tracks two flags across one sweep (`armed`: a segment may
start here but has consumed 0 chars; `open`: it has consumed ≥1) so a `/`
only completes a landing when `open`, never on a zero-length attempt.
Verified equivalent to the OLD regex translator (reconstructed standalone,
not deleted from history) across 567 hand-picked edge cases (double
slashes, embedded `\n`, empty patterns/text) plus 65,000 random-fuzzed
`(pattern, text)` pairs spanning both alphabets — zero mismatches.

Performance was iterated three times against the review's own ask ("a
timing test on a 90 KB `file_path` under 50ms") plus a MORE realistic case
(`error_hiding_blocker`'s actual 14 default excludes: 11 vendored-dir globs

- 3 fixture globs, all sharing the `**/X/**` shape) — a naive per-token
  sweep passed the first but not the second (81ms):

1. `_apply_prefix` and `_apply_star` initially used a plain O(n) Python
   loop; switched to `str.find`-driven scans, faster in isolation but WORSE
   once combined with other patterns on this repo's own dense-slash
   adversarial shape (many small `find` calls beat a tight loop only when
   boundaries are sparse).
2. The real win: a `**/<name>/**`-shaped exclude list shares its ENTIRE
   `PREFIX`+`SEGSTAR` prefix across every pattern, diverging only at the
   literal name — but each pattern recomputed that shared O(n) prefix from
   scratch. Added a `step_cache` (keyed by `(token, id(input reachable), id(text))`, scoped to one `path_matches_globs` call, safe because the
   cache and everything it references share that call's lifetime) so the
   shared prefix work runs once per candidate, not once per pattern.
3. With PREFIX/SEGSTAR now cached, `_apply_literal`'s per-position
   `reachable[j] and text[j:j+ln]==literal` loop became the dominant cost,
   because SEGSTAR's output on this dense text is itself dense (most
   positions reachable). Rewrote it to drive from `text.find(literal, pos)`
   instead: a literal like `node_modules` is typically ABSENT from the
   candidate entirely, and `find` returning "not found" is one fast
   C-level scan rather than up to `len(text)` Python-level slice
   compares. Stress-tested this specifically against the classic
   pathological shapes for naive substring search (dense overlapping
   matches, periodic near-misses) up to 640 KB — stayed linear, no hidden
   blowup reintroduced.

Final measured timings (this repo's venv): the review's own 90 KB/4-pattern
timing ask, ~25ms; the realistic 14-pattern `error_hiding_blocker` set on
the same 90 KB adversarial path, ~30ms — both comfortably under the 50ms
ask. The review's own `probe_n24r_p9_pathhang.py` reproducer, re-run
unmodified against the fix: the final `n=45_000` case (the one that used to
require `faulthandler`'s 8s watchdog + SIGKILL to recover from) now
completes in 0.48s. RED tests in
`tests/unit/utils/test_path_exclusion.py`: `TestGlobstarDoesNotCrossPartialSegments`
(the `**/secret` vs `xsecret` regression, pinned permanently) and
`TestLinearMatcherPerformance` (the review's own 90 KB/50ms ask, plus a
45,000-segment/1s sanity bound matching the review's adversarial shape).
Full `tests/unit/utils/test_path_exclusion.py` suite green (63 tests), plus
423 passing across every handler test touching `path_exclusion`
(`error_hiding_blocker`, `comment_size`, `comment_changelog`,
`qa_suppression`, `security_antipattern`, vendor-exclusion tests) — no
regressions.

**B2 direction #4 sweep (fnmatch/regex-over-glob-translated-text
elsewhere).** Grepped `src/` for other dynamic glob-to-regex translation
(`fnmatch.translate`/hand-rolled `[^/]*`-style translators) matched via
`.fullmatch()`/`.match()`. Four call sites use stdlib `fnmatch.fnmatch`
(`core/project_layout.py`, `docs_qa/checks/generated_doc_hand_edit.py`,
`utils/worktree_seed_suggestions.py`, `utils/secret_file_matching.py`):
all match a BOUNDED string (a single path component/basename, or a small
fixed-size joined window of path parts), never an attacker-supplied
unbounded `file_path` reaching a SAFETY+BLOCKING guard in the hot PreToolUse
path the way `path_exclusion.py` did — and `fnmatch.translate`'s output has
no `**`-style nested-quantifier segment logic to begin with. Not fixed;
noted here as the sweep's result rather than left silently undone. Every
other `.fullmatch`/`.match` call in `utils/` is a static, hand-written,
non-glob-derived regex against structured input (header lines, shell
tokens, bracket expressions) — a different audit (ReDoS review of
hand-written regexes), out of B2's specific scope.

**Remaining review items, not yet started:**

- **Client fail-closed for PreToolUse** (`init.sh`/hook shim): a socket
  timeout or an invalid/malformed/empty response must become a DENY with
  recovery instructions, with a narrow exact-match allowlist for
  `bin/hooks-daemon`/`.claude/hooks-daemon/bin/hooks-daemon`
  restart/status/logs/stop/start (no compound commands) so a wedged daemon
  never bricks a session. "Daemon not running" keeps its existing
  documented auto-start path.
- **M1** — the deadline clock starts at `chain.execute`, not request
  arrival; executor queueing can push a judged-late request past the
  client's 30s timeout regardless of the per-handler bound N34 added.
- **M2** — an abandoned straggler's dispatch-pool slot is released only
  when the straggler FINISHES, not when the caller gives up; enough
  concurrent stragglers deny every PreToolUse call with no way out short of
  a manual restart (and the restart command is itself a PreToolUse call).
- **M3** — fail-closed-on-raise is TAG-dependent (SAFETY+BLOCKING); several
  handlers that can genuinely deny (`curl_pipe_shell`, `dangerous_permissions`,
  `sudo_pip`, `pip_break_system`, `lock_file_edit`, +more) carry neither tag
  and so fail OPEN on a raise/timeout/saturation.
- **m1** (thread-per-handler overhead, ~12ms measured) — collapse to one
  worker thread per EVENT running the whole chain inline.
- **m2** (stragglers mutating shared state after the verdict already
  returned), **m3** (`BoundedDispatcher.run` edge cases: `thread.start()`
  raising leaks the semaphore permit; `except Exception` doesn't catch
  `BaseException`, leaving the future unresolved), **m4** (`bounded_dispatch.py`'s
  fail-open branches are invisible to `check_fail_open_inventory.py`),
  **m6** (nothing validates `deadline_seconds` stays below the client's
  socket timeout).
- **n1** ("shared pool"/"thread pool" wording in `bounded_dispatch.py`/
  `chain.py` — there is no pool, just bounded per-call threads), **n2**
  (`assert isinstance(...)` on the production path — `-O` strips asserts),
  **n4** (parametrise the chain test suite to also run under the shipped
  default `deadline_seconds`, not just `None`).
- **n3** informational only (two SAFETY+BLOCKING handlers exceed the
  review's 1s advisory threshold under 100 KB, both already under the
  harness's 5s bound; `secret_file_guard`'s is the guard-defects branch's
  known constant-factor issue) — no action needed here.
- **P1** (`github_auto_close_keywords` cache bypass) is explicitly OUT of
  this niggle's scope — routed by the coordinator to a different agent.

### N34 — ✅ Remedied — `secret_file_guard`'s linear scan has enough constant factor to blow past the chain deadline on its own

**Found while measuring N25's deadline margin, on request from the
coordinator.** `SecretFileGuardHandler` scales LINEARLY with command length
(confirmed up to 800 KB earlier under N25 Task 3 — doubling the input
roughly doubles the time), but its constant factor (~12µs/byte, on a hostile
"many small quoted tokens" command) is steep enough that size alone gets it
into trouble:

| Size | Wall-clock | % of the 20s `chain.deadline_seconds` budget                                 |
| ---- | ---------- | ---------------------------------------------------------------------------- |
| 1 MB | 12.315s    | 61.6%                                                                        |
| 4 MB | 48.958s    | 244.8% — past BOTH the 20s daemon deadline AND the 30s client socket timeout |

**This exposes a gap in N25's own deadline enforcement**, not a new bug in
`secret_file_guard` itself: `HandlerChain.execute`'s deadline check
(`core/chain.py`) runs BETWEEN handlers, in the per-handler loop, before
each one starts. It has no way to interrupt a handler that is already
running — so a single handler slow enough to exceed the deadline WITHIN its
own `matches()`/`handle()` call blows straight through the budget with no
check-in, and the client's own 30s socket timeout can still be reached
before the daemon ever responds. At 4 MB, `secret_file_guard` alone
reproduces the exact failure mode N25 set out to close: a slow handler
silently allowing everything queued behind it (via the client's ALLOW
fallback on timeout), just from ONE handler's own runtime rather than from
being queued behind others.

Originally reported per the coordinator's specific ask ("report
secret_file_guard's wall-clock at 1 MB and 4 MB so we know its margin
against the 20s deadline"), which was a measurement, not a remedy at the
time. The coordinator then asked for remedy 2 (below) to be implemented
before the security review, since the gap is the same fail-open class N25
exists to close and could not ship open.

**✅ Remedied**: remedy 2, an externally enforced per-handler deadline, plus
remedy 3 as defence in depth.

- New module `core/bounded_dispatch.py` (`BoundedDispatcher`): runs a
  handler's combined `matches()`+`handle()` call on its own DAEMON thread
  and waits on it with `Future.result(timeout=remaining)`, where `remaining`
  is whatever is left of the chain's `deadline_seconds` budget when that
  handler starts — not the handler's own execution time. `HandlerChain. execute` now routes every handler through this when `deadline_seconds` is
  set (unchanged, fully synchronous, when it is `None`). On expiry the SAME
  fail-closed verdict N25 already used applies: a `SAFETY`+`BLOCKING`
  handler not judged in time is denied, naming the handler; anything else is
  skipped with an advisory note — both pre-check (N25, between handlers) and
  this new post-dispatch-timeout case now share one `_record_unjudged`
  helper in `chain.py`.
- The overrunning call is genuinely abandoned, not killed (Python cannot
  force-stop a thread) — logged again at WARNING with its actual elapsed
  time whenever it does finish. Deliberately NOT
  `concurrent.futures.ThreadPoolExecutor`: its worker threads are
  non-daemon and CPython registers an `atexit` hook
  (`concurrent.futures.thread._python_exit`) that JOINS every one of them
  before the interpreter may exit — discovered live, via the isolated-daemon
  e2e test below: the daemon's own `stop` hung for the full straggler sleep
  before this was caught and the dispatcher rewritten onto plain
  `threading.Thread(daemon=True)` per call. Concurrency is still bounded (16
  calls at once, by default, via a semaphore): a call beyond that returns
  `DispatchSaturated` immediately rather than queuing, and is treated the
  same as a timeout.
- Remedy 3: a new `daemon.chain.max_safety_input_bytes` config key (default
  2 MiB), checked once per chain execution against the combined size of a
  handler's bulk-text `tool_input` fields (Bash `command`, Write `content`,
  Edit `old_string`/`new_string`). A `SAFETY` handler over the limit is
  denied/skipped (the same split as above) BEFORE dispatch is even
  attempted — cheaper than paying thread-dispatch overhead only to be cut
  off by the deadline regardless. Explicitly NOT the only guarantee — the
  per-handler deadline bound above already caps worst-case wall clock
  regardless of size — so it is safe to raise or disable (`null`) as long as
  `deadline_seconds` stays enforced. `secret_file_guard`'s own constant
  factor was deliberately left alone, per the coordinator: the guard-defects
  branch is rewriting `secret_file_matching` onto a shared bounded expander
  and will profile the 12µs/byte cost there.
- RED tests: `tests/unit/core/test_bounded_dispatch.py` (the dispatcher in
  isolation — completes-within-budget, times-out-without-waiting,
  stray-finishes-in-background, saturation-fails-fast) and new cases in
  `tests/unit/core/test_chain.py` (a SAFETY handler that oversleeps ITSELF
  denies within the deadline, not after its own sleep; a slow advisory-only
  handler allows with an advisory the same way; pool saturation denies; the
  size cap denies/skips/passes-through in each direction; `deadline_seconds: null` leaves an oversleeping handler fully unbounded, confirming the new
  mechanism is disabled exactly like the old one). An end-to-end test,
  `tests/integration/test_n34_deadline_probe_isolated_daemon.py`, starts its
  own isolated daemon with a 1s configured deadline and a probe handler that
  sleeps 8s, and asserts over the REAL socket that the client gets its deny
  back in well under 2s — not after 8s, and nowhere near the client's own
  30s timeout.

### N33 — a worktree agent's `secret_file_guard.exclude_paths` change had no effect after a daemon restart

**Found by the integration-B2 fix agent.** The agent was writing tests in
`worktree-integration-b2` that must name protected-looking filenames.
R-SECRET-SCRIPT-AUTHOR kept denying the writes. It added the two test files
to `secret_file_guard.options.exclude_paths` in the WORKTREE's
`.claude/hooks-daemon.yaml` and restarted the worktree's daemon. The denials
continued. It worked around it by building the filenames at runtime.

**Why (unverified):** the likeliest cause is that a sub-agent's hook calls
are served by the daemon of the Claude Code session's project root (the
main checkout), not by the worktree's own daemon. If so, a worktree config
change cannot affect that agent's own enforcement until it lands on main.
The docs say "restart the daemon" without saying WHICH daemon enforces a
worktree agent's tool calls, so the agent could not diagnose it.

**Candidate remedy:** first reproduce it and establish which daemon served
the denial (the hook log's project root and socket). Then either make the
deny reason name the config file it was judged against, or document
worktree-agent enforcement in CLAUDE/Worktree.md. Also consider an advisory
when a worktree's handler config differs from the enforcing daemon's.

### N32 — `pipe_blocker` splits at a `\|` inside double quotes and reads the next word as a pipe stage

**Found by the Plan 00463 agent.** The command
`grep -n "a\|--finish\|head-moved\|^#" CLAUDE/QA.md | bin/echd-capture --head 80`
was denied as R-PIPE-TO-HEAD. The only real pipe goes to the whitelisted
`bin/echd-capture`. The `\|` alternations inside the double-quoted grep
pattern were split as pipes, and the "stage" `head-moved` was read as `head`.
Two defects: a quoted `|` is not a pipe, and `head-moved` is not the
command `head`.

**Candidate remedy:** move pipe_blocker onto the shared shell lexer from
Plan 00464 (the shell-parser consolidation), so pipe boundaries come from
real tokenisation. Match a stage's command by whole word. RED tests: the
command above is allowed; `pytest | head -1` is still denied; and
`grep "x|y" f | head` is judged on `grep` (whitelisted), not on `y`.

### N31 — the dispatch-declaration advisory does not recognise "File to write to: <path>"

**Found by the 00467 dogfood agent.** A dispatch brief that named its report
path as `File to write to: <path>` still drew the Plan 00307
dispatch-declaration advisory saying no report destination was declared.
The advisory matches a narrower set of phrasings than briefs actually use,
so it nags on a correct dispatch, and a nag that is often wrong teaches
people to skim it.

**Candidate remedy:** recognise any phrasing that pairs a write verb or noun
("write", "report", "file", "output", "save") with a path in the brief, not
only fixed phrases. RED tests: the phrasing above is recognised, and a brief
with no path at all still draws the advisory.

### N30 — more shell code that must survive a hostile PATH depends on a PATH command

**Found by the 00467 dogfood agent**, applying the Defence Before Fix method
to the watchdog defect fixed at 766677c1 (00466 N1's follow-up). An
independent search for the same class ("shell code that must survive a
hostile or stripped `PATH` runs a command looked up on `PATH`, and its
absence silently takes a wrong branch") found four more candidates:

- `scripts/venv_bootstrap.sh:443` and `:474` (`date`). The agent reproduced
  this idiom.
- `scripts/install/venv.sh:427` (`date`).
- `scripts/install/daemon_control.sh:40-43` (`pgrep`).

These are the venv and install paths, which exist to work when the host's
tools are broken, exactly as `resolve_venv.sh` does.

**Candidate remedy:**

1. Fix each instance: use a bash builtin (`printf '%(...)T'` for dates,
   `/proc` or `kill -0` for process checks). Where there is no builtin,
   make the missing command a loud, explicit failure rather than a silent
   wrong branch.
2. The detector the method asks for: a check over the scripts that must
   survive a hostile PATH (`resolve_venv.sh`, `venv_bootstrap.sh`,
   `scripts/install/*.sh`, the `bin/` wrappers) that flags an external
   command whose failure is not handled. It could be a `shell_audit` rule, or
   a test that runs each such script's functions under an empty `PATH`. It
   must catch the original watchdog shape, verified by reverting 766677c1 in
   a scratch copy.

### N29 — `error_hiding`'s return-None-in-except check is evaded by returning a local assigned in the handler

**Found by the coordinator** reading the goal-flip agent's report. To clear the
`error_hiding` finding on a literal `return None` inside an `except` handler,
that agent assigned `None` to a local in the handler and returned the local
after the `try`. The behaviour is identical, and the detector no longer sees
it. So the check keys on syntax, not on the flow it exists to catch, and an
agent under QA pressure finds the gap on the first try. The goal-flip branch
has been told to undo the evasion and fix the code honestly.

**Candidate remedy:** judge the flow, not the token. An `except` handler that
binds a name read by a later `return`, where that name's only values are
`None` or a default and the handler logs or re-raises nothing, is the same
finding as a literal `return None`. RED tests: the evasion shape is flagged,
a handler that logs at warning or above and returns a documented sentinel is
not, and the literal form is still flagged. Then sweep the tree for existing
instances of the evasion shape, which would currently pass unseen.

### N28 — `project_containment` resolves a relative target against the payload cwd and ignores a same-command `cd`

**Found by the Plan 00464 agent** during its re-review fix round (S12). It is
an instance of 00464's own defect class: the payload `cwd` is where the
session started, not where the command runs. So `cd <elsewhere> && <write to a relative path>` was judged against the wrong directory, and the containment
verdict could be wrong in both directions.

**Remedied on the 00464 branch** (`worktree-plan-464-commit-gate-repo`,
827c45df) through the new `find_command_placements`, which every
path-judging guard is meant to share. Two sibling walkers still resolve
their own way: `reference_repo_freshness` (the 00464 agent fixes it on that
branch) and `secret_file_matching` (after the guard-defects branch merges,
in the shell-parser consolidation). Mark Remedied when 00464 lands; the
siblings are tracked in the coordinator's consolidation work.

### N27 — `skill_scan` and `tool_report` build the transcript directory name two different ways

**Found by the 00468 core agent** (report on its branch,
`subagent-reports/260924-p468-core-opus-5-5.md`). Claude Code keeps a
project's transcripts under a directory named after the project path, with
characters it cannot use in a name replaced. `skill_scan` and `tool_report`
each derive that name with their own code, and they disagree for a path
containing `.` or `_`. So for such a project one of them reads the wrong
directory, finds nothing, and reports "no data" rather than an error.

**Candidate remedy:** one helper derives the transcript directory from the
project path, pinned to Claude Code's real rule (checked against a real
`~/.claude/projects/` entry for a path with `.`, `_` and `-`). Both commands
and every other derivation site use it (sweep for the other derivations).
The helper raises, not returns empty, when the directory does not exist and
the caller asked for it. RED test: a project path with `.` and `_` resolves
to the same directory from both commands.

### N26 — `check_skill_references.py` scans zero files when run from a worktree

**Found by the 00468 core agent.** Run from any worktree, the skill
references QA check reports success after scanning 0 files. A check that
examines nothing and passes is a fail-open gate: every sub-agent's targeted
QA runs from a worktree, so the check has been silently vacuous exactly
where branches are verified.

**Candidate remedy:** find why the file discovery comes up empty in a
worktree (a `.git` file rather than a directory, or a path anchored to the
main checkout), and fix it. Separately, the check FAILS when it scans zero
files where skills exist, so a vacuous pass cannot recur. Audit the other
`scripts/qa/check_*.py` for the same "0 examined, PASS" shape and pin the
class with a test that runs each check from a worktree fixture.

### N25 — ✅ Remedied — a slow handler runs out the client's 30 s budget, and a timeout is an ALLOW for the whole PreToolUse chain

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), B1 and
m3). `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`. On a
read-side socket timeout, `.claude/init.sh` (about lines 1654-1661) emits
`hookSpecificOutput` with context only, which is an ALLOW for every non-Stop
event. So any handler that can be made slow enough bypasses every guard
behind it, not just itself. Two instances are measured:

- `destructive_git`'s `strip_inert_spans` takes 99 s on a 200 KB command.
  That is already on main.
- The guard-defects branch's interior-wildcard DP takes 31 s on a crafted
  60 KB command. That one is fixed on its branch as review 2's B1.

Fixing each slow handler one by one leaves the class open: the next
super-linear regex or DP reopens it silently.

**Candidate remedies (the class, not the instance):**

1. The daemon enforces a per-event deadline well under the client budget
   (for example 20 s for the whole chain). When it passes, the remaining
   SAFETY+BLOCKING handlers are treated as having raised, which means DENY
   with a "not judged in time" reason under N24's fail-closed rule.
   Advisory handlers are skipped with a note.
2. Fix the measured instance: `strip_inert_spans` becomes linear, with a
   timing test at 200 KB.
3. A test harness drives every SAFETY handler with large hostile inputs
   (long runs of quotes, backslashes, wildcards and nesting) under a time
   bound, so a super-linear path fails CI rather than a client.

Deliberately NOT a remedy: making the client fail closed on timeout. A
daemon that is merely slow (an overloaded host) would then block every tool
call. The deadline belongs inside the daemon, where it can tell safety
handlers from advisories.

**✅ Remedied.** All three candidate remedies landed, on the same branch as
N24 (which this depends on for its fail-closed wording):

1. `ChainConfig.deadline_seconds` (`config/models.py`) is a new config key,
   default `Timeout.CHAIN_DEADLINE_DEFAULT = 20` (seconds), threaded through
   `DaemonController.initialise()` -> `process_event()` ->
   `EventRouter.route()` -> `HandlerChain.execute()` the same narrow-slice DI
   idiom N24 used for `strict_mode`. Inside `execute()`'s per-handler loop, a
   deadline check runs before each handler: once exceeded, every remaining
   SAFETY+BLOCKING handler is denied under N24's fail-closed rule with a "not
   judged in time" reason naming the handler; every other remaining handler
   is skipped with an advisory note instead of running. `deadline_seconds: None` disables enforcement entirely. Unit coverage: `test_chain.py`,
   `test_router.py`, `test_chain_config.py`, `test_controller.py` (deadline
   reaches the router end-to-end).
2. `strip_inert_spans` (via `shell_segmentation.py`) is now linear. The root
   cause was the same shape in three places: `strip_message_bodies`'s
   segment/binary/subcommand resolution and `strip_quoted_heredoc_bodies`'s
   substitution-depth and receiving-segment lookups all re-derived
   prefix-dependent state from scratch (`command[:match_start]`) for every
   regex match, instead of advancing incrementally in the guaranteed
   left-to-right match order. Replaced with three stateful trackers
   (`_SegmentTracker`, `_SubstitutionDepthTracker`, `_LastNewlineTracker`)
   that each bound their per-match cost to the gap since the previous query.
   Reproduced review 2's exact repros directly: the 40000-`-m`-flag case
   (99.179s on main) now runs in 0.139s; the 5000-heredoc case (98.342s on
   main) now runs in 0.453s. Timing tests pinned at 200 KB in
   `tests/unit/utils/test_shell_segmentation_performance.py`; full
   `destructive_git`/`curl_pipe_shell`/`shell_segmentation` regression stays
   green.
3. `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`
   drives every `HandlerTag.SAFETY` `pre_tool_use` handler (23 of them,
   discovered via `iter_builtin_handler_classes()`, never a hardcoded list)
   with four hostile shapes — many small quoted/backslashed/wildcarded
   tokens (the shape that actually caused #2's bug: many MATCHES, not one
   giant token) and deep `$(...)` nesting — against both a `Bash` command
   payload and a `Write` file-content payload, each under a 5s bound at
   100 KB. Found no other super-linear handler. One handler,
   `SecretFileGuardHandler`, is markedly slower than its peers (~1.3s at
   100 KB vs \<0.25s for everything else) but measured LINEAR up to 800 KB
   (doubling input doubles time) — a high constant factor, not a
   superlinearity bug, so it is noted here rather than "fixed": worth a
   follow-up look if it ever becomes a real bottleneck, but out of this
   niggle's scope (which is specifically superlinear paths).

**Harness extended (guard-defects review 3 follow-up).** Review 3 found a
DIFFERENT class from the 100 KB-scale shapes above: COMBINATORIAL blowup on
a SHORT input — `echo {a,b}` x20 (110 bytes) took 36s on a guard whose bug
lives on the `guard-defects`/`463` branches, not this one.
`TestCombinatorialSmallInputShapesStayLinear` (same file) adds brace
expansion (x16/x20/x24), nested braces, `/**/` and `**/*` globs, bracket
classes, and deep `eval`/`bash -c` nesting, all under 300 bytes, applied to
both a `Bash` command and a `Write` `file_path`. It also sweeps this
repository's own `.claude/project-handlers/` (`enforce_llm_qa` included)
best-effort, via the same `ProjectHandlerLoader` the daemon uses — 28
handlers swept in total. Clean on this branch (27/27 pass, ~7s): expected,
since the vulnerable code these shapes target is not present here yet — the
harness is the "class detector" the guard-defects/463 branches fix against,
not a fix itself. Measuring `secret_file_guard`'s margin against the 20s
deadline at 1 MB/4 MB (requested alongside this) surfaced a related but
DISTINCT gap, filed separately as N34: the deadline check in `chain.py`
only runs BETWEEN handlers, so one handler slow enough within its OWN
execution is not covered at all.

### N24 — ✅ Remedied — `daemon.strict_mode` never reaches the live daemon, so every guard fails OPEN on a handler exception

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), M3), with a
live probe against this repository's own daemon. `.claude/hooks-daemon.yaml`
sets `strict_mode: true`. A Write payload that makes a handler raise
(`ValueError: no path specified`, the still-live N5 shape) came back as
`additionalContext: "Handler exception: ..."`: an ALLOW, not the strict-mode
`SYSTEM ERROR ... blocking for safety` deny.

`daemon/controller.py:959` reads `self._config.strict_mode if self._config else False`. The constructor's own comment (`:162-166`) says the `config`
parameter "is not populated by the real daemon startup path", and
`get_controller()` (`:1210`) builds `DaemonController()` with no config. So
`strict_mode` is inert in every install. Every SAFETY guard treats its own
crash as "no match". The per-guard wrapper that N11 adds to `secret_file_guard`
is the only thing between a crash and a bypass, and no other guard has one.
The N5 and N11 entries' claim that "this repository runs `strict_mode: true`,
so here the crash denied" is false.

**Candidate remedy (both halves):**

1. Plumb `config.daemon.strict_mode` into the controller's real startup path,
   through the same narrow-slice injection already used for `ChainConfig`.
   Test it through `get_controller()` and a real daemon start, not by
   constructing the controller with a config the daemon never passes.
2. Independently of `strict_mode`, the chain denies when a handler tagged
   SAFETY and BLOCKING raises, because a safety guard that crashes has not
   judged the call. That closes the class for every guard at once, including
   the review's m1 (`handle()` outside the fail-closed wrapper).

RED tests: a live-path daemon with `strict_mode: true` denies on a raising
handler; a SAFETY+BLOCKING handler that raises denies even with `strict_mode`
off; a non-safety advisory handler that raises still allows, and says so.

**✅ Remedied.** Both halves landed:

1. `DaemonController` gained a narrow-slice `_strict_mode` (Plan 00466 N24),
   the same DI idiom `_chain_config`/`_verdict_log_config` already use:
   `initialise(strict_mode=...)` sets it, `process_event` reads
   `self._strict_mode` instead of the never-populated `self._config`.
   `_build_initialised_controller` (`daemon/cli.py`) threads
   `config.daemon.strict_mode` through, so the real startup path (`cmd_start`
   → `_build_initialised_controller` → `initialise()`) now actually carries
   it. Unit coverage: `tests/unit/daemon/test_cli_strict_mode_wiring.py`
   (the `_build_initialised_controller` DI slice) and
   `tests/unit/daemon/test_controller.py` (through `get_controller()` +
   `initialise(strict_mode=...)`, both True and False).
2. `HandlerChain.execute` (`core/chain.py`) now denies unconditionally, on
   any raise from `matches()` or `handle()`, when the handler carries both
   `HandlerTag.SAFETY` and `HandlerTag.BLOCKING` — independent of
   `strict_mode`. The reason names the handler and the underlying exception
   ("evaluation error, denied for safety"), distinct from the strict-mode
   "SYSTEM ERROR" wording so a verdict log can tell the two paths apart.
   Non-safety/advisory handlers keep the pre-existing fail-open behaviour.
   Unit coverage: `tests/unit/core/test_chain.py` (5 new cases: raise in
   `handle()`, raise in `matches()`, the SAFETY-without-BLOCKING negative
   control, the non-safety negative control, and strict_mode's own wording
   still winning when both apply).

Also added an acceptance-level, live-daemon check
(`tests/integration/test_n24_strict_mode_probe_isolated_daemon.py`) that
proves the wiring end-to-end against a real daemon process, without
depending on N5's lifecycle: a probe handler raises ONLY for a payload
marked `synthetic_source: n24-probe`, which no real Claude Code session ever
sends. It started as a permanent file under this repository's own
`.claude/project-handlers/` plus a socket test against the already-running
shared daemon; both are now gone, superseded by this file, which starts its
own isolated daemon (the same pattern `test_daemon_smoke.py` uses) in a tmp
project and writes the probe's source into that tmp project's own
`.claude/project-handlers/` before starting it — a probe this narrow has no
business permanently installed in a maintainer-visible directory meant for
genuinely useful project handlers.

**NUL-byte realpath sweep (guard-defects review 2, m3, follow-up).** The
fuzzer found `sensitive_content` raising `ValueError: embedded null byte`
from a `realpath` call on 485/12000 fuzzed Write/Edit paths. With N24's
Part 2 fix this had already stopped being a silent bypass (it denies as
"evaluation error, denied for safety"), but that is the generic
chain-level catch-all, not a clear handler-specific reason — so the raise
itself is still a defect worth fixing at its source, four places:

1. `core/workspace.py`'s `ProjectRegistry.for_path`/`layout_for` both called
   `file_path.resolve()` unguarded — the shared root cause behind THREE
   handlers, since it is reached via the `Handler.layout_for()` base method:
   `error_hiding_blocker`, `security_antipattern` and `secret_file_guard`
   (via `_is_excluded`), plus `sensitive_content` itself. A new
   `_resolve_or_self` helper catches `(OSError, ValueError)` and falls back
   to the unresolved path, which safely fails to match any real declared
   project and so falls through to the same root-project/root-layout answer
   an ordinary undeclared path already gets — never a crash, matching both
   methods' own "never returns None" contract. Unit coverage:
   `tests/unit/core/test_project_registry.py::TestAnUnresolvableFilePathDoesNotRaise`.
2. `secret_file_guard`'s OWN separate raise: `utils/secret_file_matching.py`'s
   `path_is_protected` calls `os.path.realpath` and only caught `OSError`,
   not `ValueError`. Widened to `(OSError, ValueError)` — a NUL-bearing path
   cannot BE a symlink to anything, so there is nothing for the realpath
   check to discover; the raw-path glob match (which already ran first)
   still stands. Unit coverage:
   `tests/unit/utils/test_secret_file_matching.py::TestPathIsProtected::test_nul_byte_in_path_does_not_raise`.
3. `issue_filing_gate`'s `_read` calls `path.stat()` on a `gh --body-file`
   path and only caught `OSError`, not `ValueError`. Widened the same way —
   still just "could not be read", the existing refusal-not-pass verdict.
   Unit coverage:
   `tests/unit/handlers/pre_tool_use/test_issue_filing_gate.py::TestABodyItDidNot::test_a_nul_byte_in_the_body_file_path_is_denied_not_raised`.
4. `project_containment` was ALREADY safe: its `_is_within` wraps
   `Path(candidate).resolve().relative_to(container)` in a single
   `except ValueError:`, which already catches `.resolve()`'s NUL-byte raise
   the same way it catches `.relative_to()`'s mismatch — no fix needed.

`sensitive_content` itself gets a DIFFERENT, deliberate treatment beyond
just "does not crash": a NUL byte can never appear in a real filesystem
path, so a Write/Edit `file_path` carrying one is now denied OUTRIGHT with
a clear, handler-specific reason ("file_path contains an embedded NUL
byte...") — this is a classic path-truncation attack shape, and letting the
now-safe fallback silently continue to "not excluded, not the secret list,
scan whatever haystacks come back" would have been the wrong verdict even
though it would no longer crash. Checked via `matches()` before any haystack
computation runs, both `Write` and `Edit`. Unit coverage:
`tests/unit/handlers/pre_tool_use/test_sensitive_content.py::TestNulByteFilePathIsDenied`.

Swept every `HandlerTag.SAFETY` `pre_tool_use` handler (23, the same
dynamic discovery as N25 Task 3) with NUL-bearing Write/Edit/Bash payloads
after all four fixes: none raise.

The N5 and N11 entries' "this repository runs `strict_mode: true`, so here
the crash denied" claim is corrected below, in place, rather than restated
here.

### N22 — `lsp_enforcement` takes another command's argument for a grep symbol lookup

**Found by the coordinator**, live. The command was `python scripts/qa/llm_qa.py format lint ... plan_qa docs_qa ... > out.txt; grep -E '^(✅|❌)|^QA:' out.txt`. It was denied with `BLOCKED [R-LSP-SYMBOL-LOOKUP]: ... pattern 'plan_qa' looks like a symbol search`. `plan_qa` is a positional argument to `llm_qa.py`, not to `grep`. The grep's real pattern, `^(✅|❌)|^QA:`, is not symbol-shaped at all. The handler found a `grep` somewhere in the command and then took a symbol-like word from elsewhere in it. `block_once` let the identical retry through, so the cost was one wasted turn. But every "run a QA tool, then grep its capture" command is the everyday shape here, and each one is a coin toss on which word gets picked.

**Candidate remedy:** tokenise the command into its separate simple commands (`;`, `&&`, `||`, `|`), and judge only the pattern argument of a `grep`/`rg` command, never a word belonging to a different command. RED test: the command above is allowed, and `python x.py foo; grep -rn 'def my_function' src/` is still caught on `my_function`. Once 00463/00464 land, this belongs on the shared shell lexer that the parser consolidation (coordinator queue) produces.

### N21 — the semgrep QA gate passes when a rule times out

**Found by the 00414/00415 agent.** Its first version of a new semgrep rule timed out on `daemon/cli.py`, and `scripts/qa/run_semgrep_check.sh` reported PASS. A rule that times out has checked nothing for that file, so the gate fails OPEN, and the slower and more complex a rule is, the more likely it is to be silently skipped on exactly the large files it exists for.

**Candidate remedy:** a timeout, or any semgrep error entry in its JSON output (`errors[]`), fails the gate and names the rule and file. RED test: a rule forced to time out on a fixture makes the gate exit non-zero with the rule named. Check the other QA wrappers for the same "tool error reads as clean" shape, and pin the class.

### N20 — the capture-corruption auditor judges a multi-line single-quoted string one line at a time

**Found by the B1 integration agent**, as the stated limit of its fix for the auditor's backslash-continuation false positive. `scripts/qa/audit_capture_corruption.py` now joins `\`-continued lines, but a single-quoted string that spans physical lines (`echo 'x` followed by `y' >&2`) is still judged per line. So the redirect on the second line is not seen, and the echo is flagged. Nothing in the repository has that shape today, so it is latent. The same false positive that broke B1's gate would come back the first time someone writes one.

**Candidate remedy:** carry the open-quote state across physical lines for single-quoted strings too, joining the logical line the same way continuations are joined. RED test: the two-line single-quoted echo with the redirect on the second line is not flagged, and one without the redirect is.

N16 is filed on the unmerged `worktree-n466-guard-defects` branch; it joins this file at integration.

### N19 — the registry's options-collection failure is logged at debug level

**Found by the N13/N14 agent.** The handler registry's pass-1 `except Exception` logs a failure to collect a handler's options at debug level only. During the N14 work, a local variable that shadowed the new accessor made the registry silently drop EVERY handler's options, and only an existing registry test caught it before commit. In production, that failure would have looked like every handler running on defaults, with nothing at a visible log level.

**Candidate remedy:** narrow the catch to the exceptions that option collection can legitimately raise, and log anything else at error level with the handler name. If a handler's configured options cannot be applied, that is a degraded protection state and should surface in `health`. RED test: an injected failure while collecting options is visible at error level and in health.

### N18 — PlanWorkflow.core.md says the plan index is linted against one rule

**Found by the N13/N14 agent.** `CLAUDE/core/PlanWorkflow.core.md:407` and its deployed template copy say the plan index is linted "against one rule". `index-no-log` already made that false, and N13 adds `plan-stats-arithmetic` to the commit gate. The page is a deployed template pair, so it ships to clients.

**Candidate remedy:** name the rules, or better, point at the plan QA rule list, which is the source of truth, instead of counting. Change both copies of the pair together, and pin it with a doc-truth test that the page names no count that disagrees with the registry.

### N17 — `skill_opportunity_detector` never receives its configured options

**Found by the N13/N14 agent.** `_options()` reads `self.config["options"]`, which only `configure()` populates. Nothing in `src/` calls `configure()`; the registry injects options as `_<key>` attributes instead. So a configured `check_interval_days` is ignored at runtime, and only the unit tests, which call `configure()` directly, exercise the option.

**Candidate remedy:** read options the way the registry delivers them, through the shared accessor. RED test: a handler built by the real registry from a config with a non-default `check_interval_days` uses it. Then audit every handler for a `configure()`-only options path, and pin the class with a test that instantiates each handler through the registry with a non-default value for every declared option and checks that it is honoured.

### N15 — `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler

**Found by the Plan 00468 docs agent.** `daemon/cli.py` (~:6377) builds `SensitiveContentHandler()` with none of its configured options for the capture-time `scan_text` in `remote-docs add`. So the scan at the moment a page is vendored runs with no public patterns at all. That is how 28 example UUIDs were vendored into `hooks.md` without a warning, to be caught only later by the tree-wide QA scan. The secret word list happens to be found only because the configured path equals the default. This is the same class as N14: a component reads a handler's behaviour without that handler's configured options.

**Candidate remedy:** construct the handler from the project's resolved config, through the same shared handler-options accessor N14 introduces. RED test: `remote-docs add` of a page carrying a configured public-pattern match reports it at capture time, and a non-default `secret_word_list_path` is honoured. Add the construct-without-config shape to N14's class audit.

### N14 — log and payload redaction ignore a configured secret word list path

**Found by the 00414/00415 agent**, outside its brief. `utils/secret_redaction.py` `_resolve_active_path` reads `handler_cfg.get("options", {})` only when `isinstance(handler_cfg, dict)`. But `Config` coerces every handler entry to a `HandlerConfig` model (`type(c.handlers.pre_tool_use.get("sensitive_content"))` is `HandlerConfig`), so the isinstance test is never true. The daemon-wide resolver therefore never reads a configured `secret_word_list_path`, and always falls back to the default `.claude/block-words.secret`. The `sensitive_content` handler reads its own option correctly, so blocking still works. But payload capture and log redaction silently use the wrong list, or no list, in any project whose word list lives somewhere else. That is exactly how a secret term reaches a log. This repository is unaffected only because its configured path equals the default. `secret_file_matching.resolve_configured_patterns` carries a comment about this same mistake and fixed its own copy, so this is the second sighting of the class.

**Candidate remedy:** read the option through `HandlerConfig.options`, via one shared accessor for handler options that accepts either shape. RED test: with a non-default `secret_word_list_path`, a term from that list is redacted from a captured payload and a log line. Then audit every `isinstance(<handler config>, dict)` read of handler config across `src/`, and pin the class with a test or QA check that fails when handler config is read as a dict.

### N13 — the plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main

**Found by the coordinator**, through Plan 00421's agent. Opening Plan 00468 updated the README statistics bullets (468 allocated, 455 distinct) but missed the closing self-check line (`454 + 13 = 467`). `check_repo_hygiene.py`'s `plan-stats-arithmetic` check catches exactly this. But it runs only in `llm_qa.py all`, and the commit-time plan QA gate that runs on every README commit does not include it. The inconsistent index was therefore committed and pushed (d10bbf13), and was found only when an agent ran the hygiene checker by hand. The same README gate already enforces row length and the 30-row completed window at commit time.

**Candidate remedy:** run the `plan-stats-arithmetic` check in the commit-time plan QA gate whenever the staged tree touches the plan index, or move the check into plan QA and have repo_hygiene call it. Either way there is one implementation. RED test: a commit staging a README whose statistics disagree with the self-check line is denied, and names the line to fix.

### N12 — a hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it

**Found by the Plan 00467 plugin audit.** The audit fed synthetic PreToolUse payloads through `.claude/hooks/pre-tool-use` to probe handler verdicts. They carried no `synthetic_source` field, and their session ids (`plugin-audit-probe` and similar) match no known synthetic shape. So `daemon/synthetic_traffic.py` classed them as REAL traffic in `verdicts.jsonl`, including the orchestrator-simulate record that Plan 00418's enforcement decision will be read from. The marker (`SYNTHETIC_SOURCE_FIELD`, `synthetic_traffic.py:39`) is documented only in that module's docstring. CLAUDE/DEBUGGING_HOOKS.md, the handler-development guide and the agent-facing docs never mention it, so a prober cannot know to set it.

**Candidate remedy:** document the marker wherever probing a handler is taught (DEBUGGING_HOOKS.md, HANDLER_DEVELOPMENT.md, and the acceptance and playbook guidance), with a copy-paste payload that sets it. Consider a small `bin/hooks-daemon probe <event> <json>` helper that sets the marker itself. Add a test that the probing docs name the field.

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under `strict_mode: false` the chain logs the exception and allows the call. **Correction (N24, guard-defects security review 2):** the sentence that stood here — "This repository runs `strict_mode: true`, so here the crash denied" — was false. `daemon.strict_mode` never reached the live daemon (see N24, now remedied), so a crash here fell open in EVERY install, including this repository's own, whatever `hooks-daemon.yaml` declared. With N24's fix live, a crash here now denies in this repository (`strict_mode: true`) and, independently, would also deny on any install once this guard is tagged `SAFETY`+`BLOCKING` (it already is) — see N24's Part 2. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

### N9 — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

### N8 — ✅ Remedied — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Remedy:** `RuleFormatter` gained a fourth rendering, `advisory(rule)` (`core/rule.py`) — same `rule_id` and the same `Rule.verbose` teaching content as `verbose()`, headed `ADVISORY` instead of `BLOCKED`, matching the "ADVISORY:" convention several handlers already use for their own hand-rolled non-blocking reports (no new format was invented). `reference_repo_freshness.handle()` now computes `_is_blocking(session_id, subject, mode)` — a preview of `_verdict()`'s own decision, pinned to it by `TestIsBlockingMatchesVerdict` — BEFORE building the message, and `_not_verified`/`_stale` select `verbose()` when the call will actually be denied and `advisory()` when it will not (an `advise`-mode result or a `block_once` repeat). `_verdict()` itself is unchanged; it stays the sole place that decides and records.

An AST-based static sweep of every handler for `Decision.ALLOW` built from `formatter.verbose`/`terse` content (directly or through an assignment chain) found exactly one other confirmed occurrence: `reference_repo_freshness` itself — the fix above. Two structurally similar but SAFE call sites surfaced for manual review (`lint_on_edit._run_lint_command`'s `language_name` parameter, `plan_qa_edit._advisory_result`'s `findings` parameter) and were confirmed not to carry deny-shaped content. `lsp_enforcement`, named by name as a suspect, was confirmed already correct: its `block_once` repeat and `advisory` mode both return a plain `dynamic_detail` string with no rule-id/BLOCKED prefix.

The class-wide guard lives at `tests/integration/test_allow_never_carries_deny_headline.py`: it drives every handler's own declared BLOCKING acceptance test twice against the SAME instance, replicating the history-recording step `DaemonController.dispatch()` performs after every route (`daemon/controller.py`) so a handler whose block-once state lives in the shared `HandlerHistory` data layer (not an in-instance dict, e.g. `lsp_enforcement`) genuinely sees its repeat call transition to ALLOW — and asserts the repeat's `reason`/`context` never contains the `"BLOCKED ["` signature. Confirmed RED against a deliberately reintroduced defect in `lsp_enforcement` (caught it), then GREEN once reverted. `reference_repo_freshness`'s own regression coverage lives in its unit tests (`TestBlockOnce`, `TestConfiguredModes`, `TestNotVerified`) instead, RED/GREEN-verified the same way — its only DENY acceptance test declares `harness_cannot_produce` (no fixture can build a real governed checkout), so the integration harness cannot reach it.

### N7 — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — ✅ Remedied — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.

**Remedy** (remedy 1, plus remedy 2's diagnostic): every implementation
that trusted a venv interpreter's executable bit alone now proves it RUNS
first.

- Bash: `scripts/lib/resolve_venv.sh::_rv_pick_python`'s two glob loops
  (`venv-*/bin/python`, `venv-*/bin/python3`) probe each candidate with a
  new `_rv_candidate_runs` helper (`"$candidate" -c 'import sys'`) before
  accepting it, falling through to the next candidate — and eventually to
  `bin/hooks-daemon`'s venv-free path — on failure. The bound is enforced
  by a watchdog subprocess (`( sleep N; kill -KILL "$pid" )  &` + a
  blocking `wait "$pid"`), not a `sleep`-poll loop: a poll loop always
  costs at least one full poll interval even for a candidate that exits
  in milliseconds, because the first check almost always lands before the
  process has exited. Measured on this repo's own real venv `bin/python`:
  ~1005ms/candidate under an earlier `sleep 1`-poll draft, ~15-40ms/candidate
  under the watchdog. `HOOKS_DAEMON_VENV_PROBE_TIMEOUT` overrides the
  5-second default bound (mirrors `Timeout.VALIDATION_CHECK`). Both glob
  loops now report which candidate they rejected and why on stderr before
  moving on, closing remedy 2 for the bash side.
- Python: `resolve_existing_venv_python_with_diagnostics`'s shared
  `_pick_interpreter` closure (used by steps 3, 4 and 5) and step 2's
  metadata `python_path` check now all route through a new
  `_venv_interpreter_runs` helper before accepting a candidate — the SAME
  `-c 'import sys'` probe, via `subprocess.run(..., timeout=5)`. Steps 3
  and 5 (single-candidate) and step 4 (scan) each report which candidate(s)
  were executable-but-unrunnable and name the `repair` command, closing
  remedy 2 there too. The "slug-exact" fingerprint-keyed venv (step 3) is
  probed too, not exempted — #55 already showed an exact-fingerprint match
  can be container-built and still unrunnable (e.g. a shared/NFS-mounted
  `untracked/`), and this resolver only runs on a bash-side resolver-cache
  MISS, so the extra spawn never lands on the per-hook hot path.
- `resolve_existing_venv_python` (the simpler, no-diagnostics function)
  deliberately stays un-probed: it is called fresh on every user turn by
  `daemon_upgrade_detector`, which only reads `.daemon-metadata.json` next
  to the returned path and never executes it, so probing there would add
  a real hot-path cost for no correctness gain.
  `client_validator.py::validate_daemon_can_start` — the other caller,
  which DOES execute the result — already ran its own
  `subprocess.run(..., timeout=Timeout.VALIDATION_CHECK)` probe before
  doing so, so it needed no change. Both are recorded in the sibling audit
  in the delivery report.
- `check_canonical_callers.sh` was already the sibling-audit backstop for
  the bash side: it denies any OTHER shell script that iterates
  `untracked/venv-*` directly, so `_rv_pick_python` is the only bash glob
  site that needed the fix.

TDD: RED tests confirmed failing against the pre-fix code first, in both
`tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestRunnabilityProbe`
and the new `tests/integration/test_resolve_venv_runnability_probe.py`,
covering a fake executable that exits non-zero, a dangling symlink, a
hanging candidate (bound respected), fall-through to a good second
candidate, all-candidates-bad reaching the venv-free path, and the
slug-exact venv unaffected when it genuinely works.

**Follow-up defect, fixed at integration (766677c1).** The B1 full gate
failed `tests/acceptance/test_v391_field_regression.py`. That test runs the
resolver with a PATH holding only a broken `python3`. The watchdog ran
`sleep` from PATH, so with no `sleep` it went straight to `kill -KILL`. A
working venv was then rejected as "timed out after 5s", which is the v3.9.1
field case this resolver exists to survive. The branch's targeted QA had
not run that acceptance test. `_rv_wait_secs` now uses `sleep` when PATH
has one. Otherwise it waits on `read -t` against a read-write
process-substitution pipe, which needs no PATH lookup, and the kill runs
only if the full bound elapsed. Two regression tests cover a PATH with no
`sleep`: a good candidate still resolves, and a hanging one is still
bounded.

**✅ Remedied** on main (B1, 2e6483a3).
