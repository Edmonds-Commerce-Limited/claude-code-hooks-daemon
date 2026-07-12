# Plan 00154 — Recommendation

The call, the decision framework behind it, and the increment order if circumstances change. Evidence: [RESEARCH.md](RESEARCH.md); options: [RUST-TRADEOFFS.md](RUST-TRADEOFFS.md); tuning detail: [PYTHON-TUNING.md](PYTHON-TUNING.md).

## The call

**Do we even need to worry?** No. Measured against a defensible budget (hook overhead ≤ 1% of a median tool turn; no single typical event > 100 ms; RESEARCH.md §5), the system passes today: ~85 ms per tool call against multi-second turns, 51 MB RSS, ~1 minute of CPU per active agent-hour. Nothing here is user-visible.

**Rust: now, later, or never?**

- **Full daemon rewrite (Option A): never.** The entire Python daemon side costs 1.8 ms of a 45 ms event. The measured ceiling of a perfect rewrite is a ≤ 4% end-to-end win, paid for with the project's core asset — a policy engine any user or agent can read and verify in seconds. This is not close.
- **PyO3 core hybrid (Option B, core): never** — measured ceiling < 0.5 ms/event.
- **PyO3 scanner engine (Option B, scanners): later, conditional.** The one real CPU hotspot (74% of daemon CPU is `re.search`; 40 ms per 1 MB write) is a legitimate native-extension target with low transparency cost (patterns stay declarative data). But it only matters for ≥ 100 KB writes, which are rare, and pure-Python single-pass scanning (T5) should be exhausted first. Trigger condition below.
- **Compiled transport forwarder (Option C): the only Rust increment that ever pays, and not yet.** It attacks the true cost centre (~43 ms/event of bash+jq+python3 spawns, 95% of the typical path) and carries no policy, so the transparency cost is low. But half of that win is available for free (T2: remove jq), and shipping platform binaries is a permanent distribution/supply-chain tax on a project whose pitch is auditability. Earn it with telemetry first.

**What to actually do now (no rewrite, no new deps, ~days of work):**

1. **T1** — cache `is_hooks_daemon_repo` in `daemon_restart_verifier` (−1.4 ms on every Bash event in this repo; two lines).
2. **T2** — fold jq's wrapping/unwrapping into the existing python3 transport (−22 ms every event; −45 ms on status line).
3. **T4** — TTL-cache/combine the status-line git forks (render daemon-side 15.8 → ~5 ms).
4. **T3** — slim init.sh subshells (est. −5-8 ms), opportunistically.

Post-tuning expected state: typical event ~20-23 ms, status render ~25-30 ms, daemon-side ~0.4 ms. At that point the residual is almost entirely the irreducible cost of Claude Code's spawn-a-command-per-event hook contract meeting a CPython interpreter start.

## Decision framework (for revisiting this)

Rule 0 — **budget before benchmarks**: hooks are human-gated and model-paced. Overhead is a problem only if (a) a single event > ~100 ms p95 for typical payloads, (b) aggregate hook overhead > ~1% of median tool-turn latency, or (c) background CPU (status line) > ~10% of one core on target hardware. Measure with the Plan 00154 harness ([BENCHMARK-METHODOLOGY.md](BENCHMARK-METHODOLOGY.md)) on the *complaining* hardware, not this 22-core box.

Rule 1 — **never compile policy**: handlers and strategies stay readable Python, unconditionally. The trust mechanisms in RUST-TRADEOFFS.md §5 (source-readable blocks, docs generated from code, Python extension API) are the product.

Rule 2 — **compile only policy-free layers, only on evidence**: transport (Option C) and, at most, a regex *engine* behind declarative pattern tables (Option B-scanners). Precondition for either: the corresponding free win (T2 / T5) has landed and re-measurement still shows a budget violation.

Rule 3 — **quantify both sides of any proposal**: claimed ms saved × events/hour on real telemetry, versus named costs (platform binary matrix, supply-chain surface, second toolchain in QA, edge-case re-verification). If the saved time per user-hour is under a few seconds, it loses to the distribution tax automatically.

Concrete triggers that would reopen the Rust question:

- Field reports of hook latency on slow hardware (laptop/macOS) where the harness shows the *forwarder* > 100 ms p50 after T2/T3 → prototype Option C behind a bash fallback.
- Telemetry showing routine ≥ 500 KB Write/Edit payloads with users noticing the stall after T5 → prototype the PyO3 scanner engine with patterns kept as data.
- Claude Code ever offering a persistent-hook-process or socket-native hook protocol upstream → the forwarder problem dissolves for free; revisit nothing.

## First increment, if "ever" arrives

Option C (transport forwarder), scoped ruthlessly: stdin → wrap → AF_UNIX → stdout/exit-code, nothing else; daemon startup, venv resolution, CI passthrough and all error messaging remain in the readable bash path, which also serves as the automatic fallback when the binary is missing for a platform. Ship with sha256 manifest entries in the existing release bundle machinery. Re-run the Plan 00154 harness before/after and publish both numbers in the release notes.

## Loose ends handed back to the maintainer (out of research scope)

- The legacy one-shot entry `src/claude_code_hooks_daemon/hooks/pre_tool_use.py` crashes against the current config schema (`PluginLoader.load_handlers_from_config` receives a str — RESEARCH.md §6.4). Dead-or-broken code either way; consider deleting the standalone path.
- `daemon_restart_verifier`'s per-Bash-event git fork (T1) is a dogfooding-repo-only cost but a two-line fix.
- Daemon RSS settled 51 → 76 MB during the benchmark flood; a one-off long-horizon RSS check (days, via the existing daemon_stats surface) would confirm there is no slow leak. Not urgent — no growth signature was observed at session timescale beyond allocator retention.
