# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N40 — ✅ Blockers/Majors/minors/nits all remedied — adversarial security review of the N24/N25/N34 fix (2 blockers, 3 majors, 6 minors, 4 nits)

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
`controller.process_event`/`process_request` directly; the report's own
real-socket reproducer is now ALSO automated, in
`tests/integration/test_b1_surrogate_isolated_daemon.py`: an isolated daemon
with the DEFAULT handler set (no probe handler needed — B1 lives in core
dispatch) receives `git reset --hard HEAD~1 # \ud800` (B1's own manual
reproducer) over a real socket and is still denied by
`prevent-destructive-git`, plus a second case putting the same surrogate in
`file_path` (B2's own vector) and asserting the daemon returns a
well-formed verdict rather than crashing or hanging.

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

**Client fail-closed for PreToolUse — ✅ Remedied.** `init.sh`'s
`send_request_stdin` (the python3 transport embedded in every hook
forwarder) previously fell open for every event except Stop/SubagentStop on
ANY failure, including a socket timeout against a daemon B2 had already
proven could be demonstrably alive and simply stuck — the client-side half
of exactly the gap B2 exploited. Team-lead's explicit, unattended decision
(2026-09-24) superseded an earlier "the client does not fail closed"
constraint. Two new failure classes now deny for `PreToolUse` specifically,
leaving every other event and every other `PreToolUse` error type
unchanged:

1. `socket_timeout` (connect+send succeeded, the daemon was reached and is
   alive, but nothing came back within `CLAUDE_HOOKS_SOCKET_TIMEOUT`,
   default 30s).
2. A new `malformed_response` check on the SUCCESS path: the round-trip
   completed, but the bytes received are not one of PreToolUse's two
   legitimate shapes (`{}` — a real ALLOW with nothing to say, matching
   `HookResult.to_json`'s documented empty-response case — or a dict with a
   `hookSpecificOutput` key whose `permissionDecision`, if present, is one
   of the four known values). Previously the response was echoed to stdout
   completely unvalidated.

Both are DELIBERATELY narrower than "any transport failure at all":
`socket_not_found`, `connection_refused` and `invalid_hook_input` (the
daemon was never reached, or the caller's own payload never parsed
client-side) keep the existing, separately-documented fail-open path
(`ensure_daemon`'s auto-start already ran before this point) — denying
every tool call whenever the daemon is merely absent would make Claude Code
itself unusable during any daemon downtime, a materially different cost
from a rare timeout or garbled response. A new
`_is_daemon_recovery_command` allowlist (exact match only, no compound
commands) exempts `bin/hooks-daemon`/`.claude/hooks-daemon/bin/hooks-daemon`
`restart`/`status`/`logs`/`stop`/`start` from BOTH new deny paths, so a
wedged daemon can always still be restarted from inside the same session —
`bin/hooks-daemon restart && rm -rf /` is deliberately NOT exempt (the
allowlist check is a whole-string `==`, not a prefix match).

Pinned end-to-end against the REAL script (sourced, not reimplemented) in
`tests/integration/test_init_sh_pretooluse_fail_closed.py`: a real bound
AF_UNIX socket that accepts, reads the request, then never responds (the
socket_timeout/GIL-hang shape) denies for PreToolUse but leaves Stop's
existing fail-open unaffected; a socket that responds with unparseable
bytes or valid-JSON-wrong-shape both deny; the exact recovery command still
gets through under either failure (a compound variant does not); a
legitimate `{}` and a legitimate real deny both pass through byte-identical
to before; a nonexistent socket (genuinely no daemon) keeps the existing
fail-open path. Confirmed RED first: replayed the same hanging-socket
fixture against the pre-fix `init.sh` (git blob `362e2516`) and got the old
fail-open `additionalContext`-only response with no `permissionDecision`.
`shellcheck init.sh` clean; the embedded python3 block (extracted by line
range) independently `compile()`-checked and its two new helper functions
unit-tested in isolation before the end-to-end run. `.claude/init.sh` is a
symlink to `../init.sh`, so no separate deploy-sync step was needed.

**M1 — ✅ Remedied.** The chain deadline was measured from `HandlerChain. execute`'s own call, not request arrival — executor queueing between the
socket read and the worker thread actually starting was invisible to the
budget, so a request already judged late by the CLIENT's own 30s timeout
could still look on-time to the chain. `HooksDaemon._handle_client`/
`_handle_event_client` now stamp `arrival_time = time.perf_counter()`
immediately after the socket read, threaded through `_process_request` →
`DaemonController.process_request`/`process_event` → `EventRouter.route` →
`HandlerChain.execute` as a new keyword-only parameter (`None` for every
caller that predates M1, falling back to `execute()`'s own call time —
unchanged behaviour). RED tests: a stale `arrival_time` (10s in the past)
denies a SAFETY+BLOCKING handler immediately even though nothing is slow
(`tests/unit/core/test_chain.py`); omitting `arrival_time` keeps the
pre-existing behaviour. Pseudo-event dispatch and verdict logging in
`process_event` still run AFTER the chain returns and are not themselves
inside the arrival-anchored budget — a smaller, separately-tracked gap the
review's own direction treated as optional ("or run them after the response
is written"), left for a follow-up niggle rather than expanding this one's
scope further.

**M2 — ✅ Remedied.** `BoundedDispatcher`'s semaphore permit was released
only when an abandoned ("straggler") call FINISHED, never when the caller
gave up waiting on it — so enough concurrent stragglers (the review's own
16-straggler reproducer) denied every future PreToolUse call permanently,
with no way out short of a manual restart, and the restart command itself
is a PreToolUse call. Three parts:

1. *Release the slot.* `BoundedDispatcher.run` now releases its semaphore
   permit the MOMENT `future.result(timeout=...)` gives up (not when the
   straggler eventually finishes) via a new `_SinglePermit` wrapper shared
   between the waiting thread and the worker thread, guaranteeing the
   permit is released exactly once regardless of which side gets there
   first. A new dispatch can proceed immediately even while the abandoned
   call is still running.
2. *Bound the stragglers.* Releasing the permit early reopens the gap it
   used to close: nothing bounded how many abandoned calls could pile up.
   A SEPARATE `max_stragglers` cap (defaults to `max_inflight`, Single
   Source of Truth unless a caller splits them) refuses a NEW dispatch
   outright once that many stragglers are already alive, independent of
   ordinary inflight capacity. `BoundedDispatcher.straggler_health()`
   reports the live count and the oldest one's age.
3. *DEGRADED health + self-restart.* `DaemonController.get_health()` now
   reports `status: "degraded"` (with `degraded_reasons: ["stragglers"]`)
   once the straggler count reaches `daemon.chain.straggler_unhealthy_count`
   (new `ChainConfig` field, default 4), and carries the count/oldest-age/
   restart-threshold in a `stragglers` sub-dict. A new watchdog task,
   `HooksDaemon._monitor_straggler_health`, polls this every 10s and
   self-restarts (calls `shutdown()`, i.e. exits) once the OLDEST straggler
   has run past `daemon.chain.straggler_restart_after_seconds` (default
   120s) — recovery, not an outage: the client's own lazy `ensure_daemon`
   auto-start in `init.sh` brings up a fresh, zero-straggler process on the
   very next hook call.

RED-first TDD throughout: `tests/unit/core/test_bounded_dispatch.py` (permit
released immediately on timeout without double-releasing on the straggler's
own later completion; straggler count/age tracked correctly; a new dispatch
refused once the straggler cap is reached even with free inflight capacity);
`tests/unit/daemon/test_controller.py` (`get_health()` reports zero/below-
threshold/at-threshold/disabled straggler states); `tests/unit/daemon/ test_server_coverage.py` (the watchdog self-restarts past the threshold,
stays quiet below it, tolerates a `None` threshold/missing `stragglers` key/
a raising `get_health()`/a legacy controller with no `get_health()` at all,
without crashing the loop). Also folded in review m3's two `BoundedDispatcher`
edge cases while touching the same code: `thread.start()` raising no longer
leaks the semaphore permit or the thread-tracking entry, and the worker now
catches `BaseException` (not only `Exception`) so a `SystemExit`/
`KeyboardInterrupt` inside a handler resolves the future instead of leaving
it unresolved for the FULL remaining timeout.

**M3 — ✅ Remedied (narrowed scope).** Fail-closed-on-raise was TAG-dependent
(`chain.py`'s `_record_unjudged` requires both `HandlerTag.SAFETY` and
`HandlerTag.BLOCKING`), and the review found 19 PreToolUse handlers that can
genuinely deny but carried neither. Of those, 14 were COMPLETELY untagged
(no fail-closed-relevant decision had ever been made about them at all);
the other 5 (`enforce-tdd`, `qa-suppression-blocker`, `plan-*`, and 19 more
across the whole tree) already carry `BLOCKING` alone, which reads as a
deliberate-if-incomplete choice rather than an oversight — auditing that
much larger 22-handler bucket one-by-one was judged out of scope for this
niggle (see the follow-up note below) rather than rushed alongside the
other review items still open.

Of the 14 completely-untagged handlers: 6 are now `HandlerTag.SAFETY` +
`HandlerTag.BLOCKING` — `artifact_publish_blocker` (irreversible external
disclosure), `curl_pipe_shell`/`dangerous_permissions`/`sudo_pip`/
`pip_break_system`/`lock_file_edit_blocker` (team-lead's explicit list: RCE,
privilege escalation, system Python corruption, dependency-hash tampering).
The other 8 are workflow/QA gates, not dangerous-action guards, and none
gets `SAFETY`. Six are now explicitly `HandlerTag.ADVISORY` (a deliberate,
commented opt-out rather than a silent gap): `bash_safe_mode` (ships
disabled by default, has its own escape hatch), `docs_qa_commit_gate`,
`docs_qa_edit`, `plan_qa_commit_gate`, `staged_lint_gate`,
`verification_result_gate` (a heuristic detector, imperfect by its own
docstring) — each denies only under a non-default config value. The other
two, `ask_user_question_blocker` (strict mode, the shipped default, denies
unconditionally) and `validate_instruction_content` (denies unconditionally
on a pattern match, no config gate at all), deny under a DEFAULT install, so
`HandlerTag.ADVISORY` would have understated them: a full-suite run (below)
surfaced the pre-existing sibling guard
`test_declared_behaviour_matches_source.py`, which independently requires
`HandlerTag.BLOCKING` for any handler whose default behaviour denies (it
feeds `scripts/qa/check_doc_truth.py`'s ground truth for the generated
`.claude/HOOKS-DAEMON.md`). Tagged `HandlerTag.BLOCKING` instead —
satisfies both registry tests, since this test's own early-return treats
`BLOCKING` alone as an already-made fail-closed decision.

New registry test, `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`:
parametrised over every `pre_tool_use` handler, source-inspects each for a
deny signal (`HookResult.deny`/`Decision.DENY`/`Decision.BLOCK` — the same
heuristic the review's own enumeration probe used), and fails any COMPLETELY
untagged denier that carries neither `SAFETY`+`BLOCKING` nor `ADVISORY` —
opt-out-not-opt-in, so a NEW handler in this state fails the suite instead
of the gap growing silently. Deliberately does not flag the pre-existing
`BLOCKING`-only bucket (out of this niggle's narrowed scope, see above).
RED confirmed first (exactly the 14 named above failed, nothing else).
Full `pre_tool_use`/registry/chain regression stays green (4167 passed).

**Follow-up recorded here, done below:** a full audit of the 22-handler
`BLOCKING`-without-`SAFETY` bucket (`enforce-tdd`, `qa-suppression-blocker`,
`plan-qa-edit`, `comment_size`, `comment_changelog`, `dispatch_declaration`,
`merge_to_main_approval`, `plan_close_approval`, `plan_time_estimates`,
`reference_repo_freshness`, `remote_docs_*`, `require_gh_*_comments`,
`enforce_lsp_usage`, `enforce_markdown_organization`, and others) — deciding
per-handler whether each should become `SAFETY`+`BLOCKING` or explicitly
document why not — was deferred as real work this niggle did not do at the
time. See "22-handler BLOCKING-without-SAFETY audit" below for the
completed pass.

**m1 — ✅ Remedied.** Thread-per-handler dispatch added ~12ms per event
(69 thread creations for this repo's PreToolUse handler set, even when
every one of them was fast). `HandlerChain.execute` now dispatches the
WHOLE handler loop (a new private `_execute_handlers` method) as ONE call
on the shared pool when `deadline_seconds` is set, not one dispatch per
handler — `deadline_seconds=None` keeps the original zero-overhead
synchronous path unchanged. The per-handler deadline CHECK stays inline
(a cheap `time.perf_counter()` comparison, not a thread) and still
attributes "not judged in time" to a SPECIFIC handler whenever the loop is
still making progress — every handler that FINISHES, however late, is
caught exactly as before. Only when the WHOLE dispatched call itself times
out or the pool is saturated (some handler never returns at all, or the
pool has no free capacity even for the whole chain) does the deny/skip
reason name "chain" instead of a specific handler — nothing is left
running on the calling thread that could still say which one it was. An
edge case surfaced during implementation: an ALREADY-expired deadline
(e.g. a stale `arrival_time`) is handled by calling `_execute_handlers`
directly rather than dispatching it with `timeout=0.0` — every handler's
own pre-loop check sees the same already-blown deadline from the first
iteration, so nothing risks hanging, and this also avoids a genuine race
`Future.result(timeout=0.0)` would have had (whether the freshly-started
thread gets scheduled at all before the wait gives up).

Five existing tests (`tests/unit/core/test_chain.py` ×4,
`tests/unit/core/test_router.py` ×1) asserted the OLD per-handler
attribution for a slow-but-finite handler exceeding the budget; updated to
assert the new chain-level attribution instead — a deliberate behaviour
change, not a regression, and the module docstring in `test_chain.py`
records why. One real-socket E2E test
(`tests/integration/test_n34_deadline_probe_isolated_daemon.py`) needed the
same update. `_dispatch_matches_and_handle` and `_make_dispatch_call`
(the per-handler dispatch closures) were dead code afterwards and deleted.
Full targeted sweep green: `tests/unit/core/`, `tests/unit/daemon/`,
`tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`,
`tests/unit/config/` (4729 passed, 1 skipped), plus the real-socket
integration files touching chain dispatch (18 passed).
`scripts/qa/check_fail_open_inventory.py`'s rows for the two `except Exception` boundaries that moved from `execute` into `_execute_handlers`
were updated to match (boundaries unchanged, only their enclosing method).

**m3 — ✅ Remedied** (folded into M2's work above, same files): the two
`BoundedDispatcher.run` edge cases (`thread.start()` raising leaking the
semaphore permit; `except Exception` not catching `BaseException`, leaving
the future unresolved for the full timeout) are both fixed.

**m2 — ✅ Remedied.** A straggler (a handler dispatch the caller already gave
up waiting on, per M2 above) could still mutate PROCESS-LIFETIME state after
its own verdict was discarded, for a decision nobody would ever see. Added
`core/dispatch_cancellation.py`: a `DispatchCancellation` (wraps a
`threading.Event`) created once per `HandlerChain.execute()` call, bound via
a `contextvars.ContextVar` around the dispatched handler loop so nested
handler code (in a different file, on the dispatched thread) can call
`is_dispatch_cancelled()` without a parameter threaded through every
signature. `execute()` calls `cancellation.cancel()` at the exact point it
gives up on a `DispatchTimeout`/`DispatchSaturated` outcome, BEFORE building
the fallback deny/allow. Two handlers had their own state write gated on it:
`sensitive_content._compute_and_cache` (skips writing `_cached_dispatch`)
and `github_auto_close_keywords.handle` (skips `tracker.mark_disclosed`).
`lsp_enforcement` needed no change: its "spend" flows through
`DaemonController.process_event`'s iteration over `result.decisions`, which
is empty for an abandoned dispatch — the m1 one-thread-per-request redesign
already structurally closed that one. RED test:
`test_chain.py::TestDispatchCancellationReachesStragglingHandlerCode` (a
handler that sleeps past its own deadline, then checks
`is_dispatch_cancelled()` before recording a "written" vs "skipped-cancelled"
outcome), plus one regression test per fixed handler
(`test_sensitive_content.py`, `test_github_auto_close_keywords.py`).

**m4 — ✅ Remedied.** `check_fail_open_inventory.py` only ever walked
`ast.ExceptHandler` nodes, so `bounded_dispatch.py` — not even in its surface
list — and the chain-level `isinstance(outcome, DispatchTimeout)`/
`DispatchSaturated` branches in `chain.py::execute` (the fail-open decision
BoundedDispatcher.run()'s sentinel-return shape produces) were both
invisible to it. Added `bounded_dispatch.py` to `_PYTHON_SURFACES`; added
`_isinstance_dispatch_boundaries`, walking `ast.If` nodes whose test is
`isinstance(x, DispatchTimeout | DispatchSaturated)` (a new "isinstance-
dispatch" construct shape alongside the existing "except X" one). RED test
(`test_fail_open_inventory_checker.py::TestIsinstanceDispatchBoundaries`,
with a narrowing-control test proving an ordinary unrelated `isinstance`
check is NOT flagged) confirmed against the unmodified detector first. Six
new inventory rows added: `chain.py::execute::isinstance-dispatch DispatchTimeout`/`DispatchSaturated` (both `fail-open` — ALLOW when no
SAFETY+BLOCKING handler is registered) and four `bounded_dispatch.py` rows
(`run::except FutureTimeoutError`, `_run_and_release::except BaseException`,
both `not-fail-open` — they are the SOURCE of the decision, made by the
caller, not a verdict made here). Fixing n2 below (replacing the `assert`
with an explicit `elif`) split the single `isinstance-dispatch DispatchTimeout`
row that had covered both sentinels via an `else`-branch `assert` into two
independent rows, which is the more accurate shape. `check_fail_open_ inventory.py` passes clean (39/39).

**m6 — ✅ Remedied.** `ChainConfig.deadline_seconds` only enforced `gt=0`; a
configured value at or past the client's own socket timeout
(`Timeout.SOCKET_DISPATCH_ROUNDTRIP`, 30s) would reproduce the exact bypass
`deadline_seconds` exists to close — the client gives up and fails the WHOLE
chain open before the daemon's own deadline-triggered deny can be built and
sent back. Added a `model_validator(mode="after")` on `ChainConfig` that
raises `ValueError` (surfaces as `pydantic.ValidationError`) when
`deadline_seconds` is at/past `SOCKET_DISPATCH_ROUNDTRIP`, or leaves less
than a new `Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS` (5s) margin —
naming the configured value, the client timeout, and how much to lower it
by. `None` (disabled enforcement) is never checked. RED-first in
`test_chain_config.py::TestDeadlineBelowClientSocketTimeout`; includes a
test that the shipped default (`Timeout.CHAIN_DEADLINE_DEFAULT` = 20s, 10s
of margin) satisfies its own rule.

**m5 — ✅ Remedied.** Three sub-findings, all fixed:

1. *Non-monotonic measurement* was already fixed before this session
   (`362e2516`, prior to this niggle's own work): `_safety_payload_size`
   serialises the WHOLE `tool_input` dict with `surrogatepass` rather than
   summing a fixed field list, closing the MultiEdit `edits[]`/NotebookEdit
   `new_source`/`file_path` gaps the review measured.
2. *Misattributed deny reason*: the size check runs BEFORE scope/`matches()`,
   so it fires for the FIRST SAFETY+BLOCKING handler in PRIORITY order,
   whichever that is — an oversized Write got denied naming
   `prevent-destructive-git` regardless of relevance. `_apply_oversized_input`
   now builds `reason=f"chain: input too large..."` instead of
   `f"{handler.name}: ..."`, matching the existing "chain: not judged in
   time" convention. RED test
   (`test_oversized_input_deny_reason_does_not_misattribute_to_an_unrelated_handler`)
   uses two SAFETY+BLOCKING handlers and asserts NEITHER name appears.
3. *Server-side transport fail-open*: a request past
   `SocketLimit.REQUEST_BUFFER_BYTES` (16 MiB) overran
   `reader.readline()`'s own limit; the bare `ValueError` fell into
   `_handle_client`'s generic exception handler, which tried to write an
   error response and close WITHOUT draining the still-unread remainder of
   the oversized send first — on a Unix domain socket this can make the
   close send an RST instead of a clean FIN, and the client saw a raw
   `ConnectionResetError`/`BrokenPipeError` with NO response at all (real
   socket, `probe_n24r_p7_size.py`), indistinguishable from the daemon
   having crashed outright and NOT covered by `.claude/init.sh`'s
   `malformed_response` fail-closed-for-PreToolUse handling (which needs an
   actual response to act on). Added `_drain_oversized_request`: drains the
   remainder before responding, each `read()` bounded by a 0.5s
   per-read timeout (the protocol carries no length header, so silence that
   long reads as "the sender is done", not "still arriving" — the real
   client sends its whole request in one blocking call before it ever tries
   to read a response) and a running total capped at
   `SocketLimit.REQUEST_BUFFER_BYTES` so a sender that never stops writing
   cannot hang the connection either. RED test (real isolated daemon,
   `test_a_payload_past_the_socket_buffer_limit_fails_closed_for_pretooluse`,
   a genuine >16 MiB payload) confirmed the connection-reset-with-nothing
   failure first; GREEN confirms a real `{"error": ...}` response now always
   arrives.

- **n1 — ✅ Remedied.** "Shared pool"/"thread pool" wording in
  `bounded_dispatch.py` (class docstring, singleton comment),
  `chain.py` (two docstrings), `config/models.py`'s `deadline_seconds`
  field docstring, and `test_chain.py`'s module docstring all corrected:
  `BoundedDispatcher` gives every call a FRESH daemon thread, bounded by a
  shared semaphore — there is no fixed worker set and nothing is queued.
- **n2 — ✅ Remedied.** `chain.py::execute`'s
  `assert isinstance(outcome, DispatchSaturated)` (narrowing the `else` of
  the DispatchTimeout check) replaced with an explicit `elif isinstance(...)`
  and a `raise TypeError(...)` `else` — `-O` strips asserts, which would
  have left `detail` silently unbound instead of failing loudly. Test:
  `test_chain.py::TestUnexpectedDispatchOutcomeFailsLoud`, driving a fake
  `BoundedDispatcher` subclass whose `run()` returns neither sentinel.
- **n4 — ✅ Remedied.** Added `test_chain.py::TestUnderShippedDefaultDeadline`,
  parametrised over `deadline_seconds` `[None, Timeout.CHAIN_DEADLINE_DEFAULT]`
  — five representative core `execute()` behaviours (empty-chain allow,
  matches-called-on-every-handler, terminal-deny-stops-the-chain,
  raise-denies-only-in-strict-mode, first-restrictive-wins) now run under
  BOTH the synchronous path and the real production-shipped threaded
  dispatch path (a genuine thread, semaphore, and cancellation-token
  bind/reset), not just `None`.
- **n3** informational only (two SAFETY+BLOCKING handlers exceed the
  review's 1s advisory threshold under 100 KB, both already under the
  harness's 5s bound; `secret_file_guard`'s is the guard-defects branch's
  known constant-factor issue) — no action needed here.
- **P1** (`github_auto_close_keywords` cache bypass) is explicitly OUT of
  this niggle's scope — routed by the coordinator to a different agent.

**22-handler BLOCKING-without-SAFETY audit — ✅ Done.** The follow-up
deferred below (originally "22 handlers") was live-rescanned across the
FULL registry (every event, not only `pre_tool_use` — `HandlerChain.execute`'s
fail-closed logic is generic across events) and found 24 at audit time: the
21 `pre_tool_use` handlers the review named or implied, plus 3 more from
other events (`lint_on_edit` (PostToolUse), `subagent_report_path_verifier`
(SubagentStop), `failsafe_cron_blockage_suppressor` (UserPromptSubmit)) that
carry the same tag shape. Audited each individually: all 24 are workflow/QA/
governance gates (plan approval, doc placement, QA-suppression, TDD
ordering, provenance, cadence optimisation, ...) whose fail-open consequence
is "a process step did not happen", not a dangerous/irreversible ACTION —
the bar the existing SAFETY roster (destructive git, secret disclosure,
RCE-shaped constructs, write-clobbering, ...) is drawn at. None promoted;
each recorded with its own specific reason (not a copy-pasted one) in a new
`_AUDITED_BLOCKING_ONLY_REASONS` table in
`test_pretooluse_fail_closed_tagging.py`, alongside a new
`test_every_blocking_without_safety_handler_is_audited` (parametrised over
the WHOLE registry, opt-out-not-opt-in: a future handler landing here with
neither `SAFETY` nor a table row fails the suite) and a rot-guard
(`test_the_audit_table_names_only_handlers_that_still_exist_and_still_need_it`)
so a stale row — one for a handler later promoted, renamed, or removed —
fails loudly instead of reading as coverage. RED confirmed by temporarily
removing one row and observing the expected failure, then restoring it.

**Full-suite sweep, incidental to M3 — 5 pre-existing failures found and fixed.**
Running the WHOLE test suite (not just targeted files) after M3 surfaced 5
failures predating this niggle's own changes, all from earlier N24/N25/N34
work in this same plan:

1. `test_handler_config_blocking.py`'s `test_sed_blocker_prevents_inline_edits_e2e`
   and `test_disabled_handler_does_not_block_e2e` called `router.route(...)`
   directly without initialising `ProjectContext`. `enforce-project-containment`
   (`SAFETY`+`BLOCKING`) now correctly denies the WHOLE chain when it raises
   for want of it (N24's fail-closed-on-raise, working as designed) — so
   both tests were denied on `enforce-project-containment` before the
   handler under test ever ran, rather than seeing that handler's own
   verdict. Fixed by requesting the file's own pre-existing (opt-in, not
   autouse) `project_context` fixture from `conftest.py` on those two tests
   — the fixture already existed and other classes in the same file already
   used it correctly.
2. Three pending release-note callouts (`40`/`41`/`42`, written earlier in
   this plan for N24/N25) failed `test_pending_release_notes_holding_area.py`'s
   own shape check: `40`'s filename had an underscore
   (`strict_mode`), which the `NN-kebab-slug.md` naming rule rejects —
   `git mv`d to `strict-mode`. `41` and `42` both wrote `**Audience**: operators, security reviewers` — the schema requires exactly ONE of a
   fixed enum (`operators`/`handler authors`/`client projects`/`everyone`),
   not a comma list; "security reviewers" was not a recognised value at
   all. Both narrowed to `**Audience**: operators`, matching this
   directory's other daemon-behaviour notes.
3. `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/02-review-new-denials-from-strict-mode-and-safety-guards.md`
   (also written for N24) existed on disk with no row in its directory's
   `README.md` task index, failing `test_repo_hygiene_check.py`'s
   post-upgrade-index-drift rule. Added the missing row.

None of these three defects were introduced by THIS niggle's B1/B2/M3/init.sh
work; they were latent since the commits that added each file, only
surfaced now because a full (not targeted) suite run happened to be part of
verifying M3. Fixed as small, self-contained corrections rather than left
broken. Full `tests/integration/` suite green after (previously 7 failed /
4187 passed / 8 skipped).

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

N34 is taken on the `worktree-n466-n24` branch (the chain deadline cannot
interrupt a running handler) and lands with that branch. N40 is taken there too
(the fail-open classes behind that branch's security-review blockers). N41 is
taken on the N38 fix branch (the chain's remaining linear per-token cost, which
waits for the shell-parser consolidation).

### N58 — R-CHMOD-WORLD-WRITABLE denies a safe chmod when a later argument contains digits

**Found by N53 review 2.** `chmod 755 f && echo <path>` was denied as
R-CHMOD-WORLD-WRITABLE. The path was a venv directory name containing a digit
run such as `-1246-py311-`. Mode 755 is not world-writable, so the deny is a
false positive. The matcher appears to read a mode from text outside chmod's
own mode argument.

**Candidate remedy:** parse chmod's argv and judge only its mode operand,
octal or symbolic, on each chmod invocation in the command. Other words and
other commands must never be read as a mode. RED test: the reported command
is allowed, while `chmod 777 f`, `chmod o+w f` and `chmod a+w f` still deny.

### N57 — `secret_file_guard` misses a protected path reached through an earlier assignment, alias or written file

**Found by the guard-defects fix (gd6_shell2 probe).** The Bash scanner reads a
command once, forward, with no memory of what an earlier statement in the same
command bound. So four shapes reach a protected file without a deny:

- a variable assigned the path, then used in `bash -c "$V"`;
- the same, used via `eval "$V"`;
- an `alias` defined to read the file, then invoked;
- a file written earlier in the command (a redirect with the path in its
  content), then run with `sh <file>`.

These are real fail-opens, not accepted residuals.

**Candidate remedy:** this is assignment and side-effect tracking, which Plan
00464's resolver already does for git (`_substitute_known_path_vars`, disk
writes read back by path). Build one shared tracker in the shell-parser
consolidation and have both secret_file_guard and the commit gates consume
it. RED tests: the four gd6_shell2 rows through the real guard.

### N56 — Tests skip when run as root, so this container never runs them

**Found by the owner, who set the rule:** every test must run as root, and
no test may skip because the process is root. This container, and the
dogfood server, run as root. So a root-guarded skip is a test that never runs
where the work happens. Tests that skip on `os.geteuid() == 0` today:

- `tests/claude_code_hooks_daemon/install/test_skills.py:146`
- `tests/integration/test_settings_deploy_lib.py:189`
- `tests/unit/daemon/test_bootstrap_decision.py:206`
- `tests/integration/test_skipif_reasons_match_their_conditions.py:88`

Plan 00351's `test_skipif_reasons_match_their_conditions.py` also endorses
the pattern: it checks that a root skip's condition is written correctly
rather than forbidding it.

**Candidate remedy:** rewrite each test so it proves its behaviour as root.
Permission checks are ineffective for root, so use a fault that root cannot
bypass: an injected opener or os call that raises `PermissionError`, a
directory or dangling symlink in place of a file, or a read-only bind or
immutable file where one is available. Replace Plan 00351's check with a
detector that fails on any root-conditioned skip. Record the rule in the
testing standards doc.

### N55 — `register_all` ignores a handler's `get_default_enabled()` when its config block is absent

**Found by goal-flip review 8 (RV8-n3), filed at review 9's request.** When a
handler has no block in `.claude/hooks-daemon.yaml`, `register_all` registers
it as enabled whatever its `get_default_enabled()` says. So a handler that is
opt-in by design runs on an install whose config never mentions it, such as
one made by `init minimal`. The goal-flip branch changed the docs to describe
this behaviour accurately, but the underlying behaviour is still unsettled.

**Candidate remedy:** decide which source is authoritative for an absent
block: `get_default_enabled()` or "absent means enabled". Make
`register_all`, `init minimal`'s generated config and the docs agree on it.
RED test: an opt-in handler with no config block is not registered, or the
docs and the handler's own default are changed to say it is.

### N54 — Every Stop and SubagentStop pays about 50 ms rebuilding `Config()` while the config is broken

**Found by goal-flip review 8, measured again by review 9.** With an
unloadable `.claude/hooks-daemon.yaml`, five callers fall back to building a
default `Config()` on every event, and each build costs about 50 ms.
`cron_stop_enforcer` and `cron_subagent_stop_enforcer` are among them, so
every Stop and SubagentStop pays it for as long as the config stays broken.
The evidence is in `untracked/scratch/probe_gf9_cache/callers_out.txt` in the
goal-flip worktree. The config cache already caches the load failure itself;
the fallback default is what is rebuilt each time.

**Candidate remedy:** build the fallback default once per cached failure (key
it on the same `(st_mtime_ns, st_size)` signature) or share one immutable
default instance. RED test: two consecutive events on a broken config build
the default once.

### N53 — WorktreeCreate fails with exit 127 when the daemon runs `git worktree add` that succeeds from a shell

**Found by the coordinator.** An Agent dispatch with `isolation: worktree`
failed. The WorktreeCreate hook reported "Handler exception:
CalledProcessError: Command \['git', '-C', '/workspace', 'worktree', 'add',
'-b', '<branch>', '<path>'\] returned non-zero exit status 127". The same
command, run from the coordinator's shell, exits 0. It takes over 2 minutes
on this host, with 4,076 files. The main daemon's own PATH includes
`/usr/bin`, and the repo has no post-checkout hook. So the daemon runs git
in an environment where something git executes cannot be found. An agent
dispatch then fails outright, with no fallback.

**Candidate remedy:** reproduce through the handler with the daemon's real
environment. Suspects: an env the handler builds for the subprocess (PATH
or HOME stripped, or GIT_EXEC_PATH), or a timeout wrapper. Fix the root
cause. Make the handler report the command's stderr in the failure, so the
next such failure names what was not found. Check whether a slow checkout
on a loaded host needs a longer timeout. RED test: the handler, given the
daemon's environment, creates a worktree.

### N52 — The sensitive_content commit gate let a matching session UUID into a commit

**Found by N46 review 2.** Commit `3da8c1ed` on the N46 branch added a review
report containing a real session UUID. The project's `session-uuid` public
pattern matches that blob, and no `exclude_paths` entry covers
`CLAUDE/Plan/`. Yet the commit gate, which scans the added lines of staged
files, allowed the commit. Nothing later caught it either:
`check_sensitive_content.py` scans only the current tree, and
`check_git_history.py` scans metadata but not historical blobs. A `--no-ff`
merge followed by a push would have published it permanently.

**Candidate remedy:** reproduce the miss in a scratch repo first. The
reviewer's untested hypothesis is that the commit ran with a cwd or `-C`
target different from the checkout the gate diffed, which is the Plan 00464
class. Then fix the gate. Add a merge and push check that runs the public
patterns over the added lines of `git log -p <upstream>..HEAD`, since that
is exactly the window this leak survived in. RED tests: the reproduced
commit shape is denied; a merge carrying the blob is denied.

### N51 — `pipe_blocker` reads an escaped alternation inside a quoted grep pattern as a pipe into `head`

**Found by Plan 00421 review 2.** `grep -i -n "a\|HEAD\|b" file` was denied.
The `\|HEAD` inside the double-quoted pattern is a basic-regex alternation,
not a pipe. The blocker split on the `|` and matched the next word
case-insensitively against `head`. That is the N32 class (a `|` inside quotes
read as a pipe stage), plus a case-insensitive match on the producer name.

**Candidate remedy:** find pipe stages with the shared shell segmentation, so
a `|` inside any quoted span, or escaped, never splits. Match the stage's
command name case-sensitively, as bash does. RED tests: this grep is allowed;
`pytest | head` is still denied. This belongs to the shell-parser consolidation
(N41) alongside N32.

### N50 — A handler option whose name matches a method overwrites that method, and the handler then crashes open

**Found by N23 review 2.** `registry.py:592` injects each configured option onto
the handler with `setattr`. An option named like one of the handler's methods
replaces the method. For example, the pre-Plan-00288 option `human_docs_dir`, or
`pauses_path`. The handler then raises on every dispatch. For
`markdown_organization` that lets a misplaced `.md` file through.

**Candidate remedy:** never let an option overwrite a callable or any attribute
the class defines. Options go into a dedicated mapping, or the injection
refuses a name that collides with a class attribute, with a clear config error
naming the option and the handler. Known renamed options get a migration
message. RED tests: a colliding option gives a config error and never crashes
the handler; `markdown_organization` still denies with the stale option set.

### N49 — `daemon_location_guard` denies a `cd` into the daemon directory that is only text inside a quoted argument

**Found by the coordinator.** A `printf '...'` whose single-quoted string
mentioned the words cd, then the daemon directory path, was denied
R-DAEMON-DIR-CD. The command appended a note to a queue file and changed no
directory. So the guard matches the shape anywhere in the command text and
does not look for a real `cd` command.

**Candidate remedy:** judge real command heads through the shared shell
segmentation, so only an actual `cd` (or `pushd`) whose target resolves into
the daemon directory is denied. Text inside a quoted argument, a heredoc body
or a commit message is not a directory change. RED tests: the printf case is
allowed; a real `cd` and a `cd` after `&&` or `;` are still denied. This
belongs to the shell-parser consolidation (N41).

### N48 — `sed_blocker`'s git-commit exemption reaches across a newline

**Found by N38 review 2** (pre-existing, not caused by that branch). The
exemption lets `sed` through when it follows `git commit` with no command
separator in between. A newline is a command separator, but the exemption
does not treat it as one. So `git commit -m x` on one line, followed by a
line that runs `sed -i`, is allowed. The command runs sed.

**Candidate remedy:** use the shared shell segmentation, so that a newline
ends the `git commit` segment. The exemption then covers only a `sed` inside
that segment's message argument. RED tests: sed on the next line is denied;
sed after a newline inside a quoted message is still exempt. This belongs to
the shell-parser consolidation (N41).

### N47 — The ccy supervisor and Claude Code's settings.json both own effort, and they fight

**Found by the owner.** They asked for medium effort. Claude Code reads effort
from `settings.json` (`effortLevel`, and `modelSettings.<model-id>.effortLevel`
per model). The supervisor (`.claude/ccy/claude-supervise.py`) keeps its own
answer and types `/effort` over it:

- `_DEFAULT_MIN_EFFORT_LEVELS` (opus=high, sonnet=high) is a floor the
  supervisor raises live effort to. It knows nothing of `settings.json`, and
  has a second override channel of its own, the `CCY_MIN_EFFORT_LEVELS` env
  var in `ccy.env`.
- `_coupled_effort_target` sends `/effort xhigh` after EVERY `/model` switch to
  a non-top family, including the restore back to the session's own Opus. And
  the floor only ever raises. So one downgrade-and-restore cycle leaves the
  session at xhigh for good, whatever `settings.json` says.

Setting medium therefore needed two edits in two formats (`settings.json` and
`ccy.env`, commits 909f9591 and e52bd9e5). Even then the restore path still
lands on xhigh.

**Candidate remedy:** make `settings.json` the single source of truth for the
effort a model runs at.

- The supervisor resolves a family's effort from the settings Claude Code
  itself reads, in its precedence order: per-model `modelSettings` over
  `effortLevel`, project over user.
- The separate floor map and `CCY_MIN_EFFORT_LEVELS` are retired, and the
  `ccy.env` lines go with them.
- A switch back to a configured model sets that model's configured effort.
  `xhigh` compensation applies only while a downgrade leaves the session on a
  fallback model.
- The fable anchor clamp (Plan 00297) stays as a ceiling.

RED tests:

- the restore lands on the configured effort, not xhigh;
- no `/effort` is sent while live effort equals the configured effort;
- a downgrade still gets xhigh;
- a missing or unreadable settings file degrades to the current defaults with a
  logged reason.

### N46 — `budget_exhaustion_detector` fires on a tool result that merely contains budget wording

**Found by the guard-defects review-6 agent.** Reading a diff whose source
code contained the string "exceeded its byte budget" raised the "budget
exhausted" alert. That text belonged to the file under review; the agent's
own budget had not run out. So the detector matches words anywhere in tool
output. A false alarm like this teaches agents to ignore the real one.

**Candidate remedy:** match only the harness's own budget-exhaustion signal,
meaning its exact shape and source. Never match free text inside a tool
result's content, such as a file or a diff. Add a RED test that reads a file
containing the phrase and expects no alert, and keep the real signal firing.

### N45 — A NUL byte in a configured word-list path makes the never-raising secret-term lookup raise

**Found by the Plan 00421 agent** while fixing N43. A NUL byte in a HEALTHY
config's `sensitive_content.secret_word_list_path` gets through
`normalise_repo_relative_path`. It then reaches `get_cached_secret_terms`,
where `path.stat()` raises ValueError, and the code there catches only
OSError. So `get_active_secret_terms` raises, although it is documented as
never raising. It does so on every leak-vector call site: the router's debug
log, the front controller and payload capture. That is where redaction must
never fail.

**Candidate remedy:**

- Validate every configured path option at config load, and reject NUL and
  other non-path bytes with a clear config error.
- Make the term lookup honour its never-raise contract: catch ValueError
  beside OSError, and treat a list that cannot be resolved as a reported
  problem that never means "redact nothing".
- Sweep the other `Path.stat`, `open` and `resolve` calls on config-supplied
  paths for the same gap.

RED tests cover the config error and each leak-vector site.

### N44 — A PreToolUse handler raises `ValueError: no path specified` on an Edit, and the Edit goes through

**Found by the Plan 00464 agent** while editing
`src/claude_code_hooks_daemon/utils/git_command_target.py` in its worktree,
with its hooks served by the main `/workspace` daemon. The hook context
returned `Handler exception: ValueError: no path specified`, and the Edit was
allowed. That message is what `os.path.relpath("")` raises. So some handler
computes a relative path from an EMPTY candidate. The replaced text contained
`Path(xdg).joinpath(*_XDG_CONFIG_PATH)`, a `*name` shape like the
`secret_file_guard` false positive on `*words[`. So the secret-path candidate
extraction is the first suspect, but this is unverified.

Nothing identifies the handler yet: the in-memory log had already rolled
over, and an in-process run without the main config did not reproduce it.
Two defects are here:

- a handler raises on ordinary content;
- the raise fails open. That is ledger N24's class, being closed on the n24
  branch.

**Candidate remedy:** reproduce through the real chain with the project's
real config and word list. Name the handler, guard the empty candidate at its
source, and add a RED test. Also sweep for other `relpath` and `commonpath`
calls that can receive an empty or foreign path.

### N43 — Log and payload redaction is inert while the daemon runs degraded on an unloadable config

**Found by the Plan 00421 agent** while closing Task 4.9 on `worktree-d-00421`.
`secret_redaction._resolve_active_path` resolves the secret word list through
the configuration. When the config cannot load (the Plan 00421 degraded
mode), that lookup raises ValueError, and redaction falls back to inert. So a
degraded daemon writes its logs and payload captures UNREDACTED, which is
exactly when a broken config makes a protective fallback matter most. The
same root cause left degraded `sensitive_content` with no secret terms; that
was fixed on the branch by pinning the default list explicitly.

**Candidate remedy:** while degraded, redaction uses the default word list
UNION the last-known-good snapshot's lists, the same set degraded
`sensitive_content` uses. A redaction failure to resolve a list must never
mean "redact nothing". Pin it with a degraded-start test that captures a
payload containing a term and asserts the term is redacted. Being fixed on
`worktree-d-00421`.

### N42 — Quoted-heredoc blanking hides text that bash executes from the Bash command guards

**Found by the N38 review** (its M3), confirmed against real bash, and
unchanged between the old regex and the new N38 scanner. `shell_segmentation`
treats a quoted-heredoc body as inert data. Several guards then blank that
text and never judge it, among them destructive_git, pipe_blocker,
curl_pipe_shell, force-push detection and, for one shape, sed_blocker. There
are seven shapes where the blanked text is not a heredoc body at all, and
bash runs it:

- an EMPTY body (`cat > n <<'E'` with `E` on the very next line, followed by
  a command and a second `E` line), with its `<<-` form and a
  `git commit -F -` form;
- an opener inside a `#` comment;
- an opener inside a double-quoted string;
- a `<<<'E'` here-string read as an opener;
- a quoted opener inside an UNQUOTED heredoc's body;
- the same inside a multi-line double-quoted string;
- an unquoted heredoc followed by a quoted one on the same line.

In each shape, a destructive or piped command is ALLOWED. The probes are in
`untracked/scratch/probe_n38r_*`. This is a fail-open in the guards
themselves, so it is fixed now on the N38 branch and not deferred to the
consolidation.

**Candidate remedy:** recognise an opener only where bash would: outside
quotes, comments and here-strings, and not inside another heredoc's body.
Close an empty body on the first delimiter line. Keep the scan to one linear,
quote-aware pass. Pin every shape through the real chain.

### N39 — Nine unit tests fail in a whole-suite run and pass when their files run alone

**Found by the guard-defects agent** (its review-4 fix round). A plain whole
unit-suite run on `worktree-n466-guard-defects` (main merged at `e14cdca4`)
gave 9 failures. They were in `test_model_fallback_detector.py`,
`test_absolute_path.py`, `test_lookup.py` and
`test_dangerous_invocation_corpus_checker.py`. The same four files run alone
gave 105 passed, 0 failed. So some earlier test leaks state (a module global,
a singleton, the environment or the cwd) into these. The full gate passed on
`main`, so the leak depends on order or on how the suite is split across
workers.

A suite that fails in one order is a hidden defect: it can hide a real
failure behind a "flaky" label, and it breaks the first time the ordering
shifts. It has not yet been confirmed whether `main` alone reproduces it;
that is the first step.

**Candidate remedy:** reproduce it on `main` with a plain sequential run, then
bisect for the polluting test. Fix the leak at its source with real isolation
(a fixture that restores the state), not by reordering. Pin it with a test
that runs the polluter and the victim in sequence.

### N38 — The PreToolUse chain takes quadratic time on a command of quoted heredoc openers

**Found by the Plan 00463 sixth review** (its nit n6), measured on `main` and
on the 463 branch alike (`untracked/scratch/probe_463v6_chain_main_heredoc.py`).
A main-thread Bash command made of repeated `cat <<'E'` openers takes the
whole in-process PreToolUse chain 1.9 s at 16 KiB, 6.8 s at 32 KiB and 51.7 s
at 94 KiB. So the cost roughly quadruples when the size doubles. The verdict
is allow, but at 94 KiB it runs past the client's 30 s budget. Until N25's
fail-closed client lands, that timeout is itself an ALLOW for the whole chain.
After it lands, it is a false deny of a harmless command, and the daemon
keeps burning a worker thread on it either way.

The handler, or handlers, carrying the quadratic heredoc scan has not yet
been identified; profiling is the first step.

**Candidate remedy:** profile the chain per handler on the 94 KiB fixture, and
make each heredoc scan linear. The likely shape is one that re-scans the rest
of the command for each opener. Pin it with a test: the 94 KiB fixture takes
the whole chain under 2 s.

### N37 — `resolve_venv.sh` caches an override's interpreter for later callers that set no override

**Found by the Plan 00376 agent** while closing the upgrade gate's
interpreter bypass. `scripts/lib/resolve_venv.sh` writes
`untracked/.python-cmd-cache` even when the answer came from
`HOOKS_DAEMON_PYTHON` or `HOOKS_DAEMON_VENV_PATH`. A later call that sets
neither override is then served the overridden interpreter from the cache.
So a one-off override sticks, and a caller that deliberately runs without
overrides still inherits one. Layer 2 of the upgrade now works around this
with its own containment check. Every other caller still inherits it.

**Candidate remedy:** never write the cache from an override-derived answer.
Also key the cache on the absence of overrides, or skip it whenever an
override is set. RED test: resolve with `HOOKS_DAEMON_PYTHON=/x`, then with
no override, and the second call must not return `/x`. Being fixed on
`worktree-d-00376`.

### N36 — `destructive_git` denies a `grep` whose search pattern is the text of a force branch delete

**Found by the Plan 00463 agent** (review-5 fix round, its nit n9). Searching
the tree for the literal force-branch-delete command text (a grep argument,
for example `grep -rn "git branch -D" docs/`) is denied as
R-GIT-BRANCH-FORCE-DELETE. Nothing in the command deletes a branch: the
text is data given to `grep`. It is the same class as N22
(`lsp_enforcement` takes another command's argument for a symbol lookup)
and the N32 pipe split: a guard matches a dangerous shape anywhere in the
command string instead of at a command position.

**Candidate remedy:** judge destructive-git shapes only at a real command
position, using the shared shell lexer from the Plan 00464 shell-parser
consolidation. Treat a quoted argument to a known data consumer (`grep`,
`rg`, `echo`, `printf`, a git `-m` message) as data. RED tests: the grep
above is allowed; `git branch -D x`, `cd r && git branch -D x`, and
`bash -c 'git branch -D x'` are still denied.

### N35 — `daemon_sync_after_merge` judges a `cd <worktree> && git merge` against the session root's ORIG_HEAD

**Found by the Plan 00421 agent.** It ran `cd <worktree> && git merge main`
inside a worktree. The advisory then reported the MAIN checkout's own
`ORIG_HEAD..HEAD` and named `.claude/hooks-daemon.yaml` and project-handlers
as changed. The worktree merge had touched neither.

**Why:** `_is_foreign_repo` and the diff both use the hook payload's cwd,
which is the session root. They ignore the directory the command itself
`cd`s into. This is the same attribution family as N28 (project_containment
ignoring a same-command `cd`) and N33 (which daemon, or which checkout,
a worktree agent's action is judged against).

**Candidate remedy:** resolve the merge's working directory from the
command, using the shell lexer's `cd` tracking from Plan 00464 (the
shell-parser consolidation). Run the ORIG_HEAD diff in THAT repository, and
say nothing when it is a different checkout from the one the daemon
serves. RED test: `cd <other-worktree> && git merge main` emits no advisory
about the session root.

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

**Widened (Plan 00463 agent, review-5 n9):** an UNESCAPED `|` inside double
quotes trips it too, not only `\|`. The RED tests must cover both spellings.

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

**The cause, and two more instances (integration B2).** Each checker drops a
file whose path contains a noise-directory name such as `untracked` or
`worktrees`, and it tests the ABSOLUTE path. Every agent checkout lives at
`untracked/worktrees/<name>/`, so every file matches:

- `check_doc_truth.py` `_iter_markdown`: 0 docs scanned in every worktree.
  **Fixed on the B2 branch** (08c4be0e): it tests the path below `--root`.
  1785 docs scanned after, 0 violations. The test is
  `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`.
- `audit_shell.py` `_is_excluded`: it keeps 0 of the worktree's `.sh` files, so
  `shell_audit` passes vacuously. Not fixed. B2 ran it by hand over the
  relative `scripts/` and skill-scripts directories: 52 files, no violations.
- `check_skill_references.py` (this entry): `_EXCLUDED_DIRS` holds both names
  and is tested against `path.parts`, so it is very likely the same cause.
  `check_github_urls.py` tests `path.parts` the same way and should be checked.

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

### N23 — `recovery_cron_advisor` hands one request's lifecycle phase to another, through the singleton

**Found by Plan 00449's agent** while fixing the eviction race in the same handler. `matches()` stores the detected phase on the handler (`self._cached_phase`) and `handle()` consumes it. The handler is a daemon-lifetime singleton and `server.py` dispatches on a thread pool, so request B's `matches()` can overwrite the value between request A's `matches()` and `handle()`. A then advises on B's phase (CREATION guidance for a PROGRESS edit, say), and B finds the cache already cleared and detects again. It raises nothing, so no test or log shows it. This is a different class from Plan 00449's select-then-evict: per-call state parked on a shared object between two calls. It is out of that plan's scope by its own Non-Goals ("no audit of every mutable handler attribute").

**Candidate remedy:** stop caching on the instance (detect in `handle()`, or key the cache by thread with `threading.local`), with a RED test that interleaves two requests' `matches()` and `handle()`. Then treat it as a class: sweep for any `self._x` assigned in `matches()` and read in `handle()`. That shape is mechanical enough for a semgrep rule like `scripts/qa/semgrep/unlocked-eviction.yaml`.

**Checked against main after integration B2 (2026-09-24): still Open, not
fixed.** `recovery_cron_advisor.py` still declares `self._cached_phase: LifecyclePhase | None = None` in `__init__`, sets it in `matches()`
(`self._cached_phase = _detect_lifecycle_phase(...)`) and reads/clears it in
`handle()` (`cached = self._cached_phase; self._cached_phase = None`) — the
exact shape this entry names. `tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py`
has `test_matches_then_handle_uses_cached_phase` but no interleaving/
concurrency test. d-00449's `BoundedFifoMap` work (Plan 00449) fixed the
select-then-evict class across 12 sites in 10 handlers, including three
other spots in this same file, but explicitly excluded this per-call-state
class from its Non-Goals and recorded it here instead — see its report,
"Recorded, not fixed". Nothing else in integration batch B2 touches this
attribute. Remains a candidate for whoever picks up this ledger.

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

### N9 — ✅ Remedied — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

**Remedied.** `utils/git_repo.py` gained `git_visible_paths(project_root)`: one combined `git ls-files --cached --others --exclude-standard -z` call returning every path git would add, or `None` outside a git repository (callers then fall back to their pre-existing unfiltered walk). `docs_qa/corpus.py`'s `iter_markdown_paths` and `iter_corpus_paths` both filter through it; `.claude/ccy/CLAUDE.md` — deliberately untracked and gitignored, yet named in scope by `is_module_doc_path`'s own docstring — is kept via a small named exception set (`_GITIGNORED_MARKDOWN_INCLUDES`) rather than left an accidental gap, with a directory-descent rule (`_git_visible_ancestor_dirs`) so the walk still reaches it.

The class audit found a SECOND live instance of the same defect: `scripts/qa/check_doc_truth.py`'s `_iter_markdown` denylisted `.claude/ccy/plugins/marketplaces/` by name but not its sibling `cache/` directory, so a plugin's cached spec markdown could still reach `_check_shell_fences` as a false finding. Fixed the same way (filtered through `git_visible_paths`) and reproduced directly with a fixture that git-ignores `.claude/ccy/` and plants a violation inside it.

The rest of the named corpora were audited and left unmigrated, each for a stated, mechanically-pinned reason: `repo_hygiene`, `sensitive_content` and `british_english` already scan `git ls-files` directly by design (tracked-only is deliberate for hygiene/secret-scanning); `magic_values` and `error_hiding` are scoped to `src/`/`tests/`/`scripts/` only, which carry no `.gitignore` gap; `doc_snippets`'s glob set never reaches a nested `.claude/ccy/` subtree; `handler_reference` never walks a directory at all (it introspects the live `HandlerRegistry`); `plan_qa`'s `PlanTree.scan` descends only the configured plan directory via `iterdir()`, never a project-root-wide walk. `tests/unit/qa/test_qa_corpus_git_visibility_audit.py` pins this table as a ratchet: every `MIGRATED` entry is verified by AST to actually import and call `git_visible_paths`, every declared source path is checked to still exist, and every `ALLOWLISTED` entry must carry a non-trivial reason — mirroring `test_qa_package_dependency_direction.py`'s shape.

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
