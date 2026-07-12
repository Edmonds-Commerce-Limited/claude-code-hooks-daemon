# Plan 00154 — Daemon Performance Research: Findings

**Scope**: Measured runtime cost of the all-Python hooks daemon (v3.36.0, self-install mode, this repo) and the evidence base for the Rust-vs-Python decision.

All numbers below were measured live in this container on 2026-07-12 unless explicitly labelled *estimate* or *lower bound*. Reproduction commands for every number: [BENCHMARK-METHODOLOGY.md](BENCHMARK-METHODOLOGY.md). Raw data: [assets/results/](assets/results/).

**Companion documents**: [PYTHON-TUNING.md](PYTHON-TUNING.md) (no-rewrite wins), [RUST-TRADEOFFS.md](RUST-TRADEOFFS.md) (options analysis), [RECOMMENDATION.md](RECOMMENDATION.md) (the call).

---

## 1. Executive summary

1. **The Python daemon is not the cost. The bash forwarder is.** A full production PreToolUse hook event costs **~45 ms** end-to-end (p50). Of that, the daemon (socket + JSON + pydantic + 38-handler dispatch) accounts for **~1.8 ms (4%)**. The other ~43 ms is client-side process spawning: a fresh `bash` (~2 ms), sourcing `init.sh` (~13 ms), a `jq` spawn (~22-24 ms), and a `python3 -c` transport spawn (~19-21 ms) — per hook event, every event.
2. **Daemon-side dispatch is already fast.** Socket round-trip floor is 0.12 ms; a typical PreToolUse Bash event is 1.83 ms p50 — and ~1.4 ms of *that* is one handler (`daemon_restart_verifier`) forking `git remote get-url` on every Bash command (only in this repo — it early-outs in client repos). The other 36 handlers' `matches()` combined cost is ~30 µs.
3. **The only genuine CPU hotspot is regex content scanning.** py-spy over a 45 s loaded window attributes **74% of all daemon CPU to `re.search`** (the security/error-hiding/QA-suppression scanners). Cost is linear in content size: ~0.7 ms for a 10 KB write, ~40 ms for a 1 MB write (socket-measured, p50). This only bites on large `Write`/`Edit` payloads, which are rare.
4. **Memory is modest.** Fresh daemon RSS: **51.3 MB**; after ~3,500 requests including 200 × 1 MB payloads: 76 MB (peak VmHWM 300 MB during the deliberate 1 MB flood — transient buffer churn, not a leak signature at this timescale). Venv on disk: 187 MB, most of it dev/QA tooling not needed at runtime.
5. **Against any defensible latency budget, current performance is fine.** Hooks add ~85 ms per tool call (pre+post), 0.3-3% of a typical multi-second tool turn and below the ~100 ms human-perceptibility threshold for a single event. The status line is the highest-frequency surface (~0.3 renders/s observed) at 62-66 ms per render — again ~76% of it process-spawn, not Python.
6. **Verdict preview** (full argument in [RECOMMENDATION.md](RECOMMENDATION.md)): no Rust rewrite is justified by this evidence. The two cheap Python/bash fixes in [PYTHON-TUNING.md](PYTHON-TUNING.md) (§T1, §T2) would cut the hot path roughly in half with zero transparency cost. The only Rust increment that ever pays for itself is a compiled *transport-only* forwarder — and it should be considered only after the free wins land and only if the residual still matters to someone.

---

## 2. Environment

| Item           | Value                                                                                                              |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| Host           | Linux 7.0.13-200.fc44.x86_64, 22 CPUs, 98 GB RAM (container, YOLO mode)                                            |
| Python         | 3.11.2 (both system `python3` and project venv)                                                                    |
| Daemon         | v3.36.0, self-install mode, `DaemonController` (new controller) path                                               |
| Handlers       | 38 PreToolUse, 8 PostToolUse, 11 Status, 6 Stop … (live `health` query)                                            |
| Codebase       | 57,702 LOC of Python under `src/claude_code_hooks_daemon/` (97 handler modules, 72 strategy modules)               |
| Load isolation | Benchmarks ran while this session was otherwise mostly idle; heavy benches were run sequentially, not concurrently |

Caveat: this is a fast many-core dev box with a warm page cache. Laptop numbers (especially process-spawn costs) will be somewhat higher; relative proportions should hold.

---

## 3. End-to-end hot-path map

Every hook event traverses:

```
Claude Code
  └─ spawns bash wrapper (.claude/hooks/<event>)          ~2 ms      (fresh bash)
       └─ sources .claude/init.sh                          ~13 ms     (path walk, mkdir -p, exec-bit
            │                                                          throttle, hostname, env setup)
       └─ jq -c '{event: …, hook_input: .}'                ~22-24 ms  (jq process spawn + parse)
       └─ send_request_stdin → python3 -c "<transport>"    ~19-21 ms  (CPython spawn + stdlib imports)
            └─ AF_UNIX connect → daemon                    ~0.1 ms    (socket floor, measured)
                 └─ asyncio readline + json.loads          ~5-20 µs   (typical payloads)
                 └─ pydantic HookEvent.model_validate      ~2 µs      (shallow — does not traverse content)
                 └─ run_in_executor → EventRouter.route    ─┐
                      └─ handler chain (38 × matches())     ├ 0.3-1.8 ms typical;
                      └─ terminal handler handle()          ─┘ 40 ms for a 1 MB Write (scanners)
                 └─ json.dumps + socket write               ~5-20 µs
       └─ (status-line only) second jq spawn to unwrap     ~22 ms
```

Two structural observations that drive everything else:

- **The expensive stages are all *before* the daemon.** The daemon exists to avoid a ~200 ms cold Python import per event (measured lower bound, §4.6) and does so — but the wrapper re-introduces ~43 ms of spawn cost per event (`jq` + `python3` + `bash` + `init.sh`).
- **Policy logic and performance cost live in different places.** Everything a user would want to introspect (what blocks, why) is in cheap Python. The expensive part (transport) contains no policy at all. This asymmetry matters for the Rust question — see [RUST-TRADEOFFS.md](RUST-TRADEOFFS.md) §5.

---

## 4. Measured results

### 4.1 End-to-end production wrappers (as Claude Code invokes them)

50 iterations each, 3 warmups, fresh bash per iteration (`bench_forwarder.sh`). Values from run 2 (run 1 within ±7%):

| Scenario                                   | p50      | p95      | p99      |
| ------------------------------------------ | -------- | -------- | -------- |
| `pre-tool-use` wrapper, safe Bash command  | 45.4 ms  | 51.1 ms  | 52.8 ms  |
| `pre-tool-use` wrapper, 1 MB Write payload | 114.4 ms | 145.6 ms | 155.5 ms |
| `status-line` wrapper (full render)        | 61.7 ms  | 73.8 ms  | 84.3 ms  |

Client-side floors (same harness):

| Floor                                   | p50     | p95     |
| --------------------------------------- | ------- | ------- |
| bare `bash -c 'exit 0'` spawn           | 2.2 ms  | 2.5 ms  |
| `bash -c 'source .claude/init.sh'`      | 13.2 ms | 15.2 ms |
| `python3 -c 'import json, socket, sys'` | 20.9 ms | 26.2 ms |
| `jq -c '{event:…, hook_input:.}'` spawn | 24.0 ms | 29.3 ms |

Sum of floors (≈60 ms) exceeds the measured 45 ms wrapper total because `jq | python3` run concurrently in the pipeline — the spawns overlap. The status-line wrapper pays a **second** jq spawn (response unwrap), hence ~62-66 ms.

### 4.2 Daemon-side socket round-trips (wire protocol, no bash)

200 iterations (100 for subprocess-heavy events), 20 warmups, single client, sequential (`bench_socket.py`):

| Event                                            | p50      | p95      | p99      | Notes                                           |
| ------------------------------------------------ | -------- | -------- | -------- | ----------------------------------------------- |
| `_system` health (floor: no dispatch)            | 0.12 ms  | 0.25 ms  | 0.40 ms  | socket + asyncio + JSON floor                   |
| PreToolUse, safe Bash (full 38-handler chain)    | 1.83 ms  | 2.03 ms  | 2.83 ms  | ~1.4 ms is `daemon_restart_verifier` (§4.4)     |
| PreToolUse, `git reset --hard` (deny at prio 10) | 0.32 ms  | 0.49 ms  | 0.63 ms  | early terminal = cheap                          |
| PreToolUse, Write 1 KB (test file, full chain)   | 0.49 ms  | 0.77 ms  | 0.87 ms  |                                                 |
| PreToolUse, Write 10 KB                          | 0.73 ms  | 0.94 ms  | 1.28 ms  |                                                 |
| PreToolUse, Write 100 KB                         | 4.65 ms  | 7.61 ms  | 8.18 ms  | scanner-dominated                               |
| PreToolUse, Write 1 MB                           | 40.35 ms | 52.09 ms | 55.51 ms | scanner-dominated, linear in size               |
| PostToolUse, Bash result                         | 0.38 ms  | 0.55 ms  | 0.71 ms  |                                                 |
| Stop (`stop_hook_active: false`)                 | 0.61 ms  | 0.83 ms  | 0.92 ms  | transcript_path nonexistent — see caveat §6.2   |
| UserPromptSubmit                                 | 11.35 ms | 15.32 ms | 16.35 ms | `git status` subprocess in git_context_injector |
| Status (status-line render, daemon side)         | 15.75 ms | 19.47 ms | 20.64 ms | 4-5 git subprocesses in git_branch handler      |

### 4.3 Component micro-benchmarks (in-process, warm, project venv)

From `bench_components.py` (p50 per call):

| Component                               | 1 KB   | 10 KB   | 100 KB   | 1 MB      |
| --------------------------------------- | ------ | ------- | -------- | --------- |
| `json.loads` of full request            | 4.5 µs | 18.4 µs | 171 µs   | 1,355 µs  |
| `json.dumps` of full request            | 4.8 µs | 20.8 µs | 172 µs   | 2,063 µs  |
| pydantic `HookEvent.model_validate`     | 2.3 µs | —       | 2.3 µs   | 2.4 µs    |
| pydantic `hook_input.model_dump`        | 1.4 µs | —       | 1.4 µs   | 1.4 µs    |
| `security_antipattern.matches()` (scan) | 52 µs  | 430 µs  | 4,060 µs | 48,361 µs |
| `error_hiding_blocker.matches()` (scan) | 22 µs  | 39 µs   | 243 µs   | 2,368 µs  |
| `qa_suppression.matches()` (scan)       | 6.4 µs | 21.7 µs | 185 µs   | 1,641 µs  |

Pydantic is flat across sizes because `HookInput` does not deep-validate `tool_input` content — its per-request cost is negligible (~4 µs total). JSON costs ~3.4 ms round-trip at 1 MB. **The security scanner is ~48 µs/KB — by far the dominant per-byte cost.**

### 4.4 Per-handler chain attribution (PreToolUse `matches()`, in-process p50)

Top costs on a safe **Bash** input (everything not listed is < 2 µs):

| Handler                        | p50 per call | Cause                                                                                                                                                                            |
| ------------------------------ | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DaemonRestartVerifierHandler` | **1,389 µs** | forks `git remote get-url origin` on EVERY Bash command (uncached `is_hooks_daemon_repo`) — this-repo-only in effect, but the fork cost is paid before the repo check can say no |
| `RootRecursionGuardHandler`    | 10.8 µs      | multi-regex command parse                                                                                                                                                        |
| 35 other handlers combined     | ~20 µs       | trivial string/regex checks                                                                                                                                                      |

Top costs on a **10 KB Write** input:

| Handler                      | p50 per call |
| ---------------------------- | ------------ |
| `SecurityAntipatternHandler` | 427 µs       |
| `ErrorHidingBlockerHandler`  | 47 µs        |
| `QaSuppressionHandler`       | 22 µs        |
| everything else combined     | < 12 µs      |

### 4.5 Whole-daemon CPU attribution (py-spy, live daemon)

py-spy 0.4.2 attached to the live daemon (PID 26974) for 45 s at 200 Hz while `bench_socket.py` replayed the full event mix. 2,140 samples, 0 errors:

- Total GIL-busy time in window: **10.7 s / 45 s** (≈24% of one core under deliberately heavy synthetic load).
- Self-time ranking: `re.search` **7.9 s (74%)**; executor thread machinery 0.8 s; `json` encode/decode 0.55 s; everything else (asyncio, pydantic, logging, socket) < 0.1 s each.

There is no "death by a thousand cuts" profile here: one hotspot (regex scanning), one long tail of nothing.

### 4.6 Cold start, CLI, and the no-daemon counterfactual

| Measurement                                                     | Value                                        |
| --------------------------------------------------------------- | -------------------------------------------- |
| `daemon.cli restart` (stop + start + readiness), 3 runs         | 1,255-1,291 ms                               |
| `daemon.cli status` one-shot invocation                         | 305 ms                                       |
| `import claude_code_hooks_daemon` (venv, warm cache)            | 141 ms                                       |
| One-shot legacy hook entry (`hooks/pre_tool_use.py`), p50 of 20 | **≥ 198 ms** (lower bound — see caveat §6.4) |

The daemon's reason to exist is confirmed: a per-event cold Python dispatch costs ≥ 198 ms; the warm-daemon path costs 45 ms end-to-end and 1.8 ms daemon-side. But note the honest framing of the README's "20x faster" claim: **daemon-side dispatch is ~100x faster than cold spawn, yet the end-to-end win is ~4.4x** because the bash wrapper spends ~43 ms spawning `jq` and `python3` per event. The remaining headroom is in the wrapper, not the daemon.

### 4.7 Memory

| State                                                           | VmRSS   | VmHWM    |
| --------------------------------------------------------------- | ------- | -------- |
| Fresh daemon (just restarted, 1 request served)                 | 51.3 MB | 51.3 MB  |
| Same daemon after ~2,500 mixed requests incl. 200 × 1 MB writes | 76.1 MB | 299.7 MB |

- The ~300 MB high-water mark occurred during the 1 MB-payload flood (multiple transient copies per request: 16 MiB asyncio read buffer headroom, decoded string, dict, pydantic model, `model_dump()` copy, response). It returned to 76 MB — buffer churn, not unbounded growth, though the 51→76 MB settle suggests fragmentation/log-buffer retention worth a longer-horizon look (not measured over days; labelled as such).
- Venv on disk: 187 MB — but the site-packages listing shows most of that is dev/QA tooling (black, mypy, ruff, pytest, safety, twine, nltk, rich…). Runtime imports are a small subset (pydantic, yaml, jsonschema, psutil, mdformat).

### 4.8 Real-session load shape

Live `health` stats for this session's daemon (before restart): 2,515 requests in 1,063 s — but ~2,400 of those were this plan's benchmarks. The organic residue plus the observed event mix gives the cadence picture: Status ≈ 0.32 renders/s average across the window, PreToolUse dominated by tool-call rate (bursty, ~1-5/s while the agent is acting). `avg_processing_time_ms: 8.39` in that snapshot is benchmark-skewed (1 MB floods) and should not be quoted as an organic number.

---

## 5. The budget: what latency actually matters here?

Hooks fire on tool calls inside an agent loop that is human-gated and model-paced:

- A typical tool turn = model thinking/streaming (1-10 s) + tool execution (0.05-30 s). Hook overhead per tool call = PreToolUse (~45 ms) + PostToolUse (~40 ms est. from §4.1 floors + §4.2 daemon cost) ≈ **~85 ms, i.e. 0.3-3% of the turn**.
- Single-event human perceptibility threshold is ~100 ms; nothing on the typical path crosses it. The 1 MB Write path (114 ms + post) grazes it — for an operation (writing a megabyte file) that itself takes much longer to generate.
- Status line: renders are asynchronous to the conversation (no one waits on them), so its cost is pure background CPU: at the observed ~0.32 renders/s × ~64 ms ≈ **2% of one core** averaged; during heavy streaming (renders throttled by Claude Code to roughly every 300 ms) worst case ≈ 20% of one core. On a 22-core box, noise; on a 2-core laptop under load, noticeable fan-spin but not latency.
- Aggregate CPU: an active agent hour with ~500 tool calls ≈ 500 × 85 ms ≈ 42 s client-side CPU + < 2 s daemon CPU + ~25 s of status renders ≈ **~1 minute of CPU per active hour**. Real but cheap.

**Budget verdict**: a defensible budget is "hook overhead ≤ 1% of median tool-turn latency, and no single event > 100 ms at p95 for typical payloads". The system currently passes everywhere except the ≥ 1 MB Write tail — which passes the "proportionate to the operation" test instead. There is no user-visible performance problem today.

---

## 6. Caveats and things NOT measured

1. **Fast hardware bias.** 22-core container, warm caches. Process-spawn floors (the dominant cost) are 2-4x worse on older laptops/macOS; that *strengthens* the "wrapper dominates" conclusion but all absolute numbers should be re-baselined per host using the harness.
2. **Stop event realism.** The Stop benchmark used a nonexistent `transcript_path`; the real `auto_continue_stop` reads and parses the session transcript (potentially MBs of JSONL). Real Stop events will be slower than the 0.61 ms measured. Not measured because synthesising a realistic transcript risks testing a fiction; the event fires once per response, so even 50 ms would be immaterial.
3. **In-process scanner numbers vs socket totals don't perfectly reconcile.** In-process `security_antipattern` on 1 MB = 48.4 ms, yet the whole socket round-trip for a 1 MB write = 40.4 ms p50. The in-process harness instantiates handlers without the registry's config injection (language filter, exclude paths), so it scans all 11 languages' pattern sets, while the live daemon may be running a narrower effective strategy set; adaptive-loop allocation noise also inflates the in-process p50. Treat in-process scanner numbers as upper bounds for attribution, and the socket numbers as ground truth.
4. **One-shot counterfactual is a lower bound.** The legacy standalone entry (`hooks/pre_tool_use.py`) crashed after config+imports+handler construction with `AttributeError: 'str' object has no attribute 'get'` in `PluginLoader.load_handlers_from_config` (it predates the current plugins config schema). The 198 ms p50 therefore excludes dispatch+output. Side-finding for the maintainer: that legacy path is broken in this repo's config; if it is meant to be dead, deleting it would be cleaner than leaving a crashing entry point.
5. **Memory over days not measured** (session lifetime too short). The 51→76 MB settle under load suggests checking long-horizon RSS once, cheaply, via the existing `daemon_stats` status handler.
6. **macOS/arm64 not measured** (no such host available here).
7. **Benchmark self-interference**: benches ran inside a live Claude session whose own hooks also hit the daemon. Effect is small (organic load ~0.5 req/s vs bench 100s/s) and pushes measured numbers *up*, never down — conclusions are conservative.

---

## 7. Hot-surface ranking (what would matter, in order, if anything did)

1. **Per-event wrapper spawn overhead** (~43 ms × every hook event) — 95% of typical-path cost. Fixable in shell/Python ([PYTHON-TUNING.md](PYTHON-TUNING.md) §T2, §T3) or ultimately with a tiny compiled transport ([RUST-TRADEOFFS.md](RUST-TRADEOFFS.md) Option C).
2. **Status line** (62-66 ms per render, 2 jq spawns + python3 spawn client-side; 16 ms of git forks daemon-side) — highest-frequency surface, but asynchronous; pure CPU cost. Tuning: §T2, §T4.
3. **`daemon_restart_verifier` git fork on every Bash command** (1.4 ms, ~75% of the Bash-event daemon-side p50; this repo only) — one-line cache fix, §T1.
4. **Content scanners on large writes** (~48 µs/KB, 74% of daemon CPU under load) — already fine for typical payloads; single-pass/combined-regex work (§T6) or, at the extreme, a native regex engine (Option B in RUST-TRADEOFFS) if very large writes ever become routine.
5. Everything else — asyncio, JSON, pydantic, routing — is measured noise (< 0.2 ms/event combined).
