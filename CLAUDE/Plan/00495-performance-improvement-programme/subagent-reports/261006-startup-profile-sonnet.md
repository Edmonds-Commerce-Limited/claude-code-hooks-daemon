# Startup profile: why the status bar is slow at session start

Date: 2026-10-06. Host: 8 cores, load average 27-40 throughout (another agent's pytest batches). Wall times are therefore inflated 3-5x; CPU seconds (process_time, plus child CPU for the chain table) are the load-robust metric and are what the version comparison uses. Raw samples, harness scripts and the cProfile dump are in `/workspace/untracked/scratch/startup-profile/`. The throwaway worktrees, venvs, client projects and every daemon I started were removed or stopped; the live /workspace daemon was never touched.

## Verdict

1. There is no single regression jump. Daemon-process start CPU has grown steadily with every release: 1.0 s (v3.30/v3.40) -> 1.5 s (v3.58) -> 2.0 s (v3.65) -> 2.5 s (v3.68 and HEAD), 2.5x. Against `CLAUDE/Performance/BASELINE.md` (cold restart 1.26 s on 22 idle cores, import 141 ms) the same start is now about 2.5 s CPU on any host, with import alone 0.6 s CPU.
2. The status line does NOT wait on SessionStart. It waits on daemon start (`ensure_daemon` polls up to 15 s, `DAEMON_STARTUP_TIMEOUT=150` deciseconds). Under host load 30, cold start took 15-30 s wall, so the status line either showed "DAEMON FAILED / still starting" at the 15 s deadline or arrived very late.
3. On this (dogfood) repository SessionStart is a separate, much larger cost: with the repo's own config the chain needs about 6-8 s of CPU (14-18 s wall under load), dominated by `docs-qa-sweep` and `plan-qa-sweep`. It overruns the 20 s dispatch budget, which is exactly the "dropped 16 handlers" symptom the coordinator saw. With the shipped example config (a typical client) SessionStart is cheap (1.6 s wall vs 0.8 s at v3.40).

## 1. Daemon process start (what the status line blocks on)

Method: `phases.py` runs the same steps as the forked daemon child in `cli.py` (import cli, `Config.find_and_load`, `_build_initialised_controller` including handler registry and the CLAUDE.md injector, `prewarm_indexes`) in a foreground process, 5 interleaved runs per version, each version using its own example config in a throwaway git project (venv per version, `uv pip install -e` of a worktree at the tag). Table cells are median [min-max]. CPU is seconds. Every sample ran while another agent's pytest batch was active (load 30-39); there was no quiet-host sample.

| Version | total CPU        | import CPU       | Config load CPU  | controller build CPU | total wall (loaded) | host load  | example yaml |
| ------- | ---------------- | ---------------- | ---------------- | -------------------- | ------------------- | ---------- | ------------ |
| v3.30.0 | 0.99 [0.91-2.01] | 0.41 [0.37-1.13] | 0.18 [0.16-0.38] | 0.38 [0.34-0.50]     | 3.74 [1.80-10.40]   | 32 [31-35] | 15 KB        |
| v3.40.0 | 1.03 [0.94-1.23] | 0.44 [0.37-0.48] | 0.25 [0.23-0.33] | 0.35 [0.32-0.42]     | 4.51 [1.47-21.20]   | 32 [31-35] | 18 KB        |
| v3.50.0 | 1.19 [1.12-2.53] | 0.53 [0.48-1.01] | 0.28 [0.25-0.58] | 0.44 [0.35-0.93]     | 8.75 [2.51-37.82]   | 32 [31-39] | 19 KB        |
| v3.58.0 | 1.51 [1.46-1.67] | 0.56 [0.48-0.59] | 0.43 [0.40-0.47] | 0.55 [0.53-0.60]     | 6.76 [5.11-12.13]   | 32 [32-37] | 33 KB        |
| v3.62.0 | 1.58 [1.38-3.04] | 0.52 [0.46-1.25] | 0.46 [0.38-0.90] | 0.58 [0.54-0.89]     | 9.67 [3.47-21.15]   | 33 [32-39] | 36 KB        |
| v3.65.0 | 2.04 [1.73-3.71] | 0.50 [0.45-1.28] | 0.57 [0.47-1.30] | 0.90 [0.81-1.13]     | 10.40 [3.09-29.99]  | 32 [32-35] | 46 KB        |
| v3.68.0 | 2.53 [2.23-2.81] | 0.63 [0.57-0.71] | 0.87 [0.69-0.98] | 1.08 [0.90-1.19]     | 13.65 [4.12-24.85]  | 33 [31-37] | 57 KB        |
| HEAD    | 2.55 [2.22-2.74] | 0.59 [0.53-0.68] | 0.84 [0.79-1.07] | 1.03 [0.88-1.10]     | 10.96 [4.09-13.63]  | 33 [31-37] | 58 KB        |

Wall spread is meaningless for ranking (load noise 3-37 s); the CPU column is the signal. Config load and controller build grew about 4.7x and 2.7x; import only 1.4x. The growth tracks the example config size (15 KB -> 58 KB, 3.8x): more handlers and options per release, parsed by a pure-Python YAML loader several times (below). The biggest per-release steps are v3.50 -> v3.58 (config 19 -> 33 KB), v3.58 -> v3.65 and v3.65 -> v3.68 (about +0.5 s CPU each).

End-to-end through the real `status-line` hook on a cold daemon (HEAD, load 24-32, tests running): status line returned after 14.8-15.2 s, which is the hook's own 15 s start deadline (it printed "DAEMON FAILED / daemon is still starting"); a second attempt directly after took a further 14.5-16.5 s. A direct `cli start` took 15.1 s wall at load 33 for about 2.6 s CPU. Warm status line: 0.29 s (idle) and 0.75-1.06 s while a SessionStart chain was running in the same daemon, so a running chain slows but does not block it.

### Where the start CPU goes (HEAD, cProfile on the shipped example config; cProfile inflates absolute figures about 2x)

| Contributor                                                                                     | cumulative (profiled)    | notes                                                                                                                                                                      |
| ----------------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| YAML `safe_load` (pure-Python `SafeLoader`; `yaml.__with_libyaml__` is True but not used)       | 2.33 s over 4 loads      | `Config.load` runs 3 times in `find_and_load`/`load_or_default` plus once more; measured on the 87 KB repo yaml: SafeLoader 0.130 s vs CSafeLoader 0.010 s per parse (13x) |
| `handlers/registry.discover` (walks and imports every handler module)                           | 1.70 s, 4 calls          | 3 of the 4 calls cost 1.63 s; it is rerun instead of reused                                                                                                                |
| `claude_md_injector.inject` -> `mdformat.text` formatting the CLAUDE.md                         | 1.55 s (1.14 s mdformat) | measured unprofiled: 0.39 s CPU on this repo's 115 KB CLAUDE.md, every daemon start                                                                                        |
| Package imports (`claude_code_hooks_daemon/__init__` -> `core/__init__`, pydantic model builds) | 1.61 s                   | `import cli` 0.59 s CPU unprofiled; 53 pydantic model constructions cost 1.33 s; 964 `re.compile` calls cost 1.18 s                                                        |
| pydantic `validate_python` of the config (`validate_handler_dependencies`)                      | 2.35 s over 3 loads      | includes the YAML parse above                                                                                                                                              |

Using the repo's own 87 KB config the total is 2.7-3.1 s CPU (vs 2.55 s with the 58 KB example).

## 2. SessionStart chain (dogfood config, current main)

Method: `chain_timing.py` builds the controller on a clone of this repository at HEAD (own process, own project, never the live daemon), wraps every SessionStart handler's `matches`/`handle`, and runs the chain sequentially without the 20 s budget so late handlers are measured rather than dropped. Wall is loaded (28-35), "CPU+kids" includes child-process CPU (git, etc.). Pytest batches were running for all rounds.

| Handler (HEAD, repo config)   | wall r1 / r2 / r3 (s) | CPU+kids r1 / r2 / r3 (s) |
| ----------------------------- | --------------------- | ------------------------- |
| docs-qa-sweep                 | 7.66 / 10.18 / 7.07   | 4.33 / 4.15 / 4.13        |
| plan-qa-sweep                 | 3.69 / 4.07 / 3.20    | 1.72 / 1.79 / 1.76        |
| tool-disable-advisor          | 1.01 / 1.18 / 1.70    | 0.59 / 0.65 / 0.66        |
| persistent-cron-assertor      | 0.93 / 1.01 / 0.61    | 0.53 / 0.48 / 0.41        |
| guard-config-drift            | 0.99 / 0.42 / 0.60    | 0.71 / 0.27 / 0.30        |
| gitignore-safety-checker      | 0.99 / ~0 / ~0        | 0.44 / ~0 / ~0            |
| ccy-supervisor-integrity      | 0.46 / 0.46 / 0.47    | 0.23 / 0.25 / 0.22        |
| secret-file-hygiene-checker   | 0.44 / 0.78 / 0.42    | 0.23 / 0.23 / 0.21        |
| failsafe-cron-session-advisor | 0.39 / ~0 / ~0        | 0.21 / ~0 / ~0            |
| git-upstream-checker          | 0.29 / 0.12 / 0.12    | 0.12 / 0.06 / 0.05        |
| remote-docs-staleness         | 0.12 / 0.11 / 0.14    | 0.08 / 0.06 / 0.09        |
| all others (21 handlers)      | each < 0.04           | each < 0.01               |
| Chain total                   | 17.1 / 18.4 / 14.4    | about 8.5 / 8.0 / 7.9     |

Earlier, with the real 20 s dispatch budget active, the chain overran in both rounds (21.1 s and 20.1 s) and the straggler thread finished 23.5 s after the budget expired, so handlers late in priority order (plan-qa-sweep, secret-file-hygiene-checker, docs-qa-sweep, model-fallback-detector, session-actions-directive, monorepo-detector, config-optimisation-reminder) were dropped. This matches the coordinator's list. Note that handlers recompute everything on every SessionStart: docs-qa-sweep (4.1 CPU-s) and plan-qa-sweep (1.75 CPU-s) repeated at the same cost in every round, so there is no cache or staleness short-circuit.

Comparison with an older version using the shipped example config (typical client), round 2, loaded host:

| Version | handlers in chain | chain wall | controller build wall | slowest handler                 |
| ------- | ----------------- | ---------- | --------------------- | ------------------------------- |
| v3.40.0 | 10                | 0.82 s     | 1.34 s                | version-check 0.81 s            |
| v3.58.0 | 15                | 2.15 s     | 1.62 s                | contract-staleness 1.01 s       |
| HEAD    | 26                | 1.57 s     | 1.59 s                | persistent-cron-assertor 0.59 s |

So for a client project SessionStart has not blown up; the regression is specific to configs that enable the QA sweeps (this repository). Network-touching handlers (`version-check`, `git-upstream-checker` fetch) cost 0.1-1.4 s wall here even on a loopback/local origin; against GitHub from a real machine they add network latency to every SessionStart (not measurable in this sandbox).

## 3. Does the status line wait on SessionStart or on daemon start?

On daemon start. `.claude/hooks/status-line` calls `ensure_daemon` (start and poll up to 15 s for the socket), then one request. On a warm daemon it never queues behind SessionStart: status fired at +0.3 s, +3 s and +8 s into a running SessionStart chain finished in 0.86, 0.75 and 1.06 s. One experiment appeared to show a 14.5 s block, but that was a confound (the daemon had not finished its cold start; the preceding SessionStart hook had returned "daemon is still starting"). The owner's slow status bar at session start is the cold daemon start, plus CPU contention while SessionStart handlers run in the same process just after.

## 4. Bisection

No single commit or plan: costs grow smoothly with the release (config size 15 -> 58 KB, handlers 10 -> 26 in SessionStart, 4x config parses). The largest single steps by CPU are v3.50 -> v3.58, v3.62 -> v3.65 (+0.5) and v3.65 -> v3.68 (+0.5); a finer commit bisect inside those ranges is possible with `phases.py` if wanted. The docs-qa-sweep and plan-qa-sweep SessionStart handlers (plan-tree and documentation QA reports at session start) are new since the v3.40 era and are the cause of the 20 s budget overrun on this repository.

## 5. Ranked fix candidates

Daemon process start (blocks the status line; currently about 2.5-3 s CPU, baseline 1.26 s):

1. Parse the YAML once and reuse the parsed result, and use `yaml.CSafeLoader` (fall back to `SafeLoader`): about 0.35-0.5 s CPU saved (4 pure-Python parses at 0.09-0.13 s each become one at about 0.01 s).
2. Run `handlers/registry.discover` once and share the result (it is run 4 times, 1.6 s of 1.7 s profiled): about 0.3-0.5 s CPU.
3. Skip the CLAUDE.md `mdformat` pass when the generated block is byte-identical to the existing one (hash compare), or run it after the socket is up: about 0.4 s CPU on this repo (less on clients with a small CLAUDE.md).
4. Start serving first, then do non-essential work (docs regeneration, `prewarm_indexes`, deferred imports of reference_repos, plan_qa, docs_qa) behind the socket: removes whatever remains from the status line's critical path; the real status-line wait is "time to socket bound".
5. Reduce import cost (lazy-import of heavy handlers/pydantic models, avoid 964 `re.compile` at import by caching or lazy compile): about 0.2-0.3 s CPU.
6. Raise or make adaptive the hook's 15 s start deadline, or show a distinct "starting" status text instead of "DAEMON FAILED" on a loaded host; no CPU gain but fixes the visible failure mode.

Together items 1-3 should bring start CPU from about 2.5 s to about 1.5 s; item 4 decouples the status line from everything past config load.

SessionStart chain (does not block the status line but does inflate CPU and drops handlers on this repo):

1. Cache `docs-qa-sweep` and `plan-qa-sweep` results keyed by a cheap fingerprint of their inputs (tree mtimes or git tree hash) and the last report, so a SessionStart with unchanged inputs costs milliseconds: about 5.9 CPU-s (14 s wall under load) saved per session start.
2. Run those sweeps in a background thread or after the SessionStart response (report on the next prompt) so the chain stays well under its 20 s budget and no handlers are dropped.
3. Order or budget the chain so cheap, high-value handlers (session-actions-directive, model-fallback-detector, secret-file-hygiene-checker) run before the sweeps, and give the sweeps their own sub-budget.
4. Take `tool-disable-advisor`, `persistent-cron-assertor`, `guard-config-drift` (0.4-1.0 CPU-s each, about 1.8 CPU-s together) off the hot path with the same fingerprint cache.
5. `git-upstream-checker` and `version-check`: do the network fetch asynchronously with a short timeout.

Status line:

1. Nothing wrong in the render path itself (warm 0.29 s, 15.75 ms daemon-side per BASELINE.md). Its latency is the daemon start (above). If cold start cannot be made fast enough, print a cheap local fallback text immediately (from a cached last-known line) while the daemon starts, instead of blocking up to 15 s.
2. Warm status during a running chain costs 0.75-1.06 s vs 0.29 s idle (CPU contention); keep SessionStart CPU low (candidates 1-4 above) to stop this.

## Caveats

No quiet-host samples were obtainable (load never below about 24); sample counts: 5 per version for the CPU series, 1-2 for end-to-end hook runs, 3 chain rounds for HEAD. Wall times are unusable for ranking; CPU ratios between versions are consistent in spread. The 87 KB repo config chain numbers apply only to configs that enable the QA sweeps. This sandbox has no external network, so the cost of the network fetches in real use is not measured.
