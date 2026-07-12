# Plan 00154 — Python/Shell Tuning Catalogue (no rewrite)

Wins available **without any Rust and without losing a line of introspectable Python**. Ordered by measured impact. All baseline numbers reference [RESEARCH.md](RESEARCH.md) §4; each item states expected magnitude, effort, and risk honestly — items marked *estimate* were not prototyped.

Summary: T1 + T2 together cut the typical hook event from ~45 ms to ~20-23 ms (measured components, arithmetic combination) and the status-line render from ~64 ms to ~30 ms. That is more end-to-end win than any Rust daemon rewrite could deliver (the entire daemon side is only 1.8 ms).

---

## T1. Cache `is_hooks_daemon_repo` in `daemon_restart_verifier` — −1.4 ms on every Bash event (this repo)

**Measured**: `DaemonRestartVerifierHandler.matches()` costs 1,389-1,458 µs p50 per Bash PreToolUse because it forks `git remote get-url origin` (`daemon/validation.py:is_hooks_daemon_repo`) on **every** Bash command. That single handler is ~75% of the 1.83 ms Bash-event daemon-side p50. The repo's remote URL cannot change under a running daemon in any way that matters.

**Fix**: memoise per `workspace_root` (module-level dict or `functools.lru_cache` on the resolved path) — one fork per daemon lifetime instead of one per Bash command. Also benefits any other caller of `is_hooks_daemon_repo`.

**Magnitude**: daemon-side Bash event p50 1.83 ms → ~0.4 ms (−78%). End-to-end: −1.4 ms of 45 ms (~3%) — small absolutely, but it is the single largest daemon-side line item and a two-line change.
**Effort**: trivial. **Risk**: near zero (stale cache only if someone re-points `origin` mid-daemon; a restart heals it).

## T2. Eliminate `jq` from the hook wrappers — −22-24 ms on every event; −44-48 ms on status line

**Measured**: each `jq` spawn costs 22-24 ms p50 (§4.1). Every wrapper spawns jq once to wrap stdin (`jq -c '{event: …, hook_input: .}'`); the status-line wrapper spawns it **twice** (wrap + response unwrap). The wrapper *already* spawns a `python3 -c` transport process — which can do the wrapping and unwrapping itself in microseconds (json.dumps of the same payload: 4.8-20.8 µs, §4.3).

**Fix**: extend `send_request_stdin`'s inline Python to accept the event name as an argument and build `{"event": $1, "hook_input": <stdin>}` itself; for status-line, extract `.text` in the same process. jq remains a dependency only for the error paths in `emit_hook_error` (or those too move into the transport script).

**Magnitude** (arithmetic from measured floors, pipeline overlap means realised win is somewhat less than the raw 22 ms): typical event ~45 → ~28-33 ms; status line ~64 → ~35-40 ms.
**Effort**: moderate — touches `init.sh` + 11 wrappers + their tests; the JSON-never-through-shell-variables invariant must be preserved (pass via stdin, not argv).
**Risk**: medium. This is the safety-critical transport; it needs the existing forwarder acceptance tests plus a careful review of control-character handling. All logic stays in readable shell/Python.

## T3. Slim the `init.sh` hot path — est. −5-8 ms per event

**Measured**: `source init.sh` alone costs 13.2 ms p50 (§4.1) — before any daemon traffic. Visible contributors in the source: several `$(subshell)` spawns (`dirname`/`cd`/`pwd`, `hostname`, `tr` pipelines in `_get_hostname_suffix`), an unconditional `mkdir -p` per event, the exec-bit self-heal `stat` probe, and conditional `git remote` checks on the self-install path.

**Fix directions**: replace `tr` pipelines with bash parameter expansion (`${var,,}`, `${var// /-}`); skip `mkdir -p` when the directory exists (`[[ -d … ]] ||`); short-circuit the repo-detection subshells when `hooks-daemon.env` already answers the question.

**Magnitude**: *estimate* −5-8 ms of the 13.2 ms (individual line items not separately measured — profile with `bash -x` + timestamps before committing to a number).
**Effort**: small-moderate. **Risk**: medium — init.sh guards many edge cases (macOS, containers, worktrees); each shortcut needs its scenario test.

## T4. Batch/TTL-cache the status-line git subprocesses — daemon-side render 15.8 → ~4-6 ms (est.)

**Measured**: the Status event costs 15.75 ms p50 daemon-side (§4.2); `git_branch.py` forks up to 5 git processes per render (`rev-parse --show-toplevel`, `branch --show-current`, `status --porcelain=v2 --branch`, `stash list`, plus one-time default-branch detection). At ~2-3 ms per git fork, the forks are essentially the whole cost.

**Fix directions** (independent, combinable):
(a) single combined call — `git status --porcelain=v2 --branch --show-stash` yields branch name, ahead/behind, counts AND stash count in one fork;
(b) a 1-2 s TTL cache keyed by repo toplevel — renders arrive every ~300 ms under streaming, so a 2 s TTL cuts ~85% of forks with imperceptible staleness (the pattern already exists in this handler: default-branch cache, TTL-gated background fetch).

**Magnitude**: *estimate* daemon-side render → ~4-6 ms; combined with T2 the full render drops ~64 → ~25 ms. Note the render is asynchronous — this is a CPU-churn win (laptop battery/fan), not a latency win.
**Effort**: small. **Risk**: low (staleness ≤ TTL; icons already tolerate stale remote refs by design).

## T5. Single-pass / combined-alternation content scanning — est. 2-5× on large writes

**Measured**: scanners cost ~48 µs/KB (security) + ~2.4 µs/KB (error-hiding) + ~1.6 µs/KB (QA-suppression); 74% of all daemon CPU under load is `re.search` (§4.5). Each strategy's patterns are applied one `re.search` at a time over the full content.

**Fix directions**: per-language, join patterns into one alternation with named groups (one pass instead of N); pre-filter with a cheap `any(keyword in content …)` gate before expensive patterns; short-circuit `matches()` on first hit (scan currently collects *all* violations even in `matches()`, which only needs a boolean — `handle()` can re-collect on the rare deny path).

**Magnitude**: *estimate* 2-5× on the scan, i.e. 1 MB write 40 → 10-20 ms. Irrelevant below 100 KB (already < 1 ms at 10 KB).
**Effort**: medium (touches 11 language strategies' pattern tables + tests). **Risk**: medium — alternation semantics must be verified per pattern (anchors, flags); worth doing only if large-file writes are shown to be common.

## T6. `orjson` for socket encode/decode — −1-3 ms only at MB payloads

**Measured**: stdlib JSON costs 3.4 ms round-trip at 1 MB, 5-40 µs at typical sizes (§4.3). orjson is ~5-10× faster (*published figures, not measured here*).

**Magnitude**: immaterial for typical events; −2-3 ms on the already-scanner-dominated 1 MB path. **Effort**: trivial. **Risk**: low, but it adds a compiled dependency — which mildly contradicts the pure-introspectable posture for near-zero gain. **Not recommended** unless T5 lands first and someone still cares about the MB tail.

## T7. Things measured and deliberately NOT worth doing

- **uvloop / socket-layer tuning**: the no-dispatch floor is 0.12 ms p50 (§4.2). There is nothing to win.
- **Pydantic removal/replacement**: validate+dump = ~4 µs/request, flat to 1 MB (§4.3). Noise.
- **Handler-chain restructuring (dict dispatch, priority buckets)**: 35 of 38 `matches()` calls cost < 2 µs each; the whole chain minus T1's fork is ~30 µs. Noise.
- **Lazy imports / cold-start work**: cold restart is 1.26 s and happens once per session/upgrade; `import claude_code_hooks_daemon` is 141 ms. Fine as is.
- **Executor-hop removal** (dispatch inline on the event loop): saves ~0.1-0.8 ms but forfeits the loop's responsiveness during 40 ms scans and the concurrency safety the executor provides. Bad trade.

## Not fixable in Python: the transport-spawn floor

After T2/T3, each event still pays ~2 ms bash + ~19-21 ms CPython interpreter start for the transport (§4.1) — that is the *irreducible floor of spawning CPython per event*, and Claude Code's hook contract (spawn a command per event) means some process must start each time. Options beyond Python: a compiled transport binary (see [RUST-TRADEOFFS.md](RUST-TRADEOFFS.md) Option C) or upstream hook-protocol changes (out of this project's control). This boundary is exactly where the Rust conversation legitimately starts — and it contains zero policy logic.
