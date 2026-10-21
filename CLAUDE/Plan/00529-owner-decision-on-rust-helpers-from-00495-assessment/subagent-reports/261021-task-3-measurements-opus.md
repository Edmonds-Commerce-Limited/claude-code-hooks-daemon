# Plan 00529 Task 3: relay vs bash on the hot hooks, under concurrency, and Rust candidates

Measurement and analysis only. No tracked file other than this report was changed, the daemon was not restarted, and the transport was not toggled.
Host: 8 cores, Linux, Python 3.11, the live daemon on `/workspace` (pid 1540071, relay enabled, 86 PreToolUse / 16 PostToolUse / 18 Status handlers).
All runs were made after the one `llm_qa.py` run present at the start had finished (load average 0.4 to 3 during the runs).

## Headline

- **Client side, per call: the relay costs 4.3 to 5.6 ms CPU, and the bash path 79 to 82 ms CPU, on every hot event** (about 16 times less).
- **At 16 concurrent sessions, the bash path saturates the host. The relay does not.** On the client side the bash path used 2.73 cores against 0.16 for the relay. Status-tick median latency was 1.17 s against 41 ms, and 274 of 480 status ticks ran late on the bash path.
- **The cost has moved into the daemon.** At 16 sessions the daemon used 0.52 of a core (17 CPU-s in 32 s). About 70% of that went on PreToolUse Bash, which takes about 50 ms CPU per call in-process. The daemon is one Python process, so this rate (a tool call every 2 s per session) reaches its one-core ceiling at about 30 sessions. Status latency already rises from 12 to 34–41 ms median at 8–16 sessions, because ticks queue behind the 50 ms chains.
- **The biggest single lever is a Python fix, not Rust.** `prevent-destructive-git` re-parses the whole command once per pattern (18 patterns), which costs 17–19 ms for any command containing "git". Parsing once per call cut PreToolUse Bash from 49.5 to 31.9 ms CPU (−36%), measured.

## 1. Per-call cost, relay vs bash (60 interleaved reps per row, 5 warm-ups)

Script: `untracked/scratch/t3/bench.py` (payloads in `payloads.py`), raw output in `percall.json` / `percall.txt`.
The script spawns one fresh forwarder (`/workspace/.claude/hooks/<event>`) per call, with the payload on stdin:

- **Client CPU** is the delta of `getrusage(RUSAGE_CHILDREN)` user+sys. It covers bash, init.sh subshells, the python3 transport or the relay.
- **Wall** is the elapsed time around the call.

How the bash path was forced (I read the generated guards first):

- **pre/post-tool-use:** `HOOKS_DAEMON_RELAY_BINARY=/nonexistent`. The guard's `-x` test then fails and it falls through to init.sh and python3.
- **status-line:** that variable does NOT reach the bash path. The Plan 00542 fast path prints the loud red line instead. The legacy path was reached with `HOOKS_DAEMON_EVENTS_DIR=<empty dir>` (no socket, so it hands off to init.sh).

Payloads:

- A realistic shape with a fake session id `00000000-0000-4000-8000-…`, a nonexistent transcript path, and `synthetic_source=manual-probe` / `probe_as=main`, so the verdict log files them as synthetic.
- Bash: `git -C /workspace log --oneline -5 && ls -la …`.
- Edit: a small edit to an existing .py file.
- Write: a 4 KB new test .py file.
- PostToolUse Bash: one with stdout.
- Status: a full Claude Code status payload.

| Event                | Path  | Client CPU ms median / p90 | Wall ms median / p90 |
| -------------------- | ----- | -------------------------- | -------------------- |
| Status line          | relay | 5.62 / 6.69                | 12.3 / 14.8          |
| Status line          | bash  | 79.97 / 88.34              | 87.3 / 104.3         |
| PreToolUse Bash      | relay | 4.53 / 5.16                | 49.9 / 58.6          |
| PreToolUse Bash      | bash  | 79.69 / 89.02              | 120.2 / 141.3        |
| PreToolUse Edit      | relay | 4.60 / 5.30                | 18.6 / 35.9          |
| PreToolUse Edit      | bash  | 81.90 / 90.64              | 96.2 / 124.1         |
| PreToolUse Write 4KB | relay | 4.37 / 5.07                | 46.6 / 54.6          |
| PreToolUse Write 4KB | bash  | 79.38 / 87.95              | 117.6 / 143.0        |
| PostToolUse Bash     | relay | 4.34 / 5.13                | 12.7 / 15.4          |
| PostToolUse Bash     | bash  | 80.11 / 87.23              | 87.0 / 97.8          |

The script also recorded a per-batch daemon CPU delta (`/proc/<pid>/stat`), but that figure includes other sessions' traffic and has a 10 ms tick resolution. The in-process numbers in section 3 are the dependable daemon figures.

### The client floor: where the relay's 4.5 ms goes (`floor.py`, `variants.txt`, 60 reps)

| Variant                                                                                  | CPU ms median | Wall ms median |
| ---------------------------------------------------------------------------------------- | ------------- | -------------- |
| `bash -c true` (bash start alone)                                                        | 1.41          | 1.7            |
| relay binary exec'd directly (no bash)                                                   | 0.80          | 39.9           |
| forwarder copy as deployed (`SCRIPT_DIR="$(cd "$(dirname …)" && pwd)"` before the guard) | 4.29          | 40.6           |
| same guard with `SCRIPT_DIR` moved below it                                              | **2.19**      | 40.0           |
| raw Python socket round trip, PreToolUse Bash (daemon wall only)                         | 0.10          | 39.8           |
| raw Python socket round trip, PostToolUse Bash                                           | 0.11          | 7.5            |

Half of the relay path's client CPU is the `SCRIPT_DIR` command substitution (a subshell plus a `dirname` fork). It runs before the relay guard and the guard never uses it. The status-line forwarder has no such line before its fast path. Its 5.6 ms comes from bash, the `read -d ''`, the payload edits and the `$(relay …)` subshell.

## 2. Concurrency (N simulated sessions, 30 s each, `conc.py`, raw in `conc.txt` and `conc-*.json`)

Each session runs two threads:

- A status tick at 1 Hz.
- Every 2 s, a PreToolUse Bash followed by a PostToolUse Bash.

Each session has a phase offset and its own fake session id. Client CPU is the `RUSAGE_CHILDREN` delta over the window. Daemon CPU is the `/proc/<pid>/stat` delta, and the idle baseline for it was 0.27–0.44 CPU-s per 30 s. Host busy is from `/proc/stat`, where 8 cores over a 32 s window is about 256 CPU-s.

| N   | Path  | Client CPU-s (cores) | Daemon CPU-s (cores) | Host busy CPU-s | Status wall median / p90 / max ms | PreToolUse wall median / p90 ms | Late ticks (status/tool) |
| --- | ----- | -------------------- | -------------------- | --------------- | --------------------------------- | ------------------------------- | ------------------------ |
| 0   | idle  | 0                    | 0.27–0.44            | 15.8–26.7       |                                   |                                 |                          |
| 1   | relay | 0.30 (0.01)          | 1.14 (0.04)          | 19.3            | 12.2 / 52.0 / 64                  | 43.1 / 52.7                     | 0 / 0                    |
| 1   | bash  | 4.61 (0.15)          | 1.14                 | 27.9            | 84.7 / 96.3 / 146                 | 116.7 / 129.8                   | 0 / 0                    |
| 4   | relay | 1.21 (0.04)          | 3.97 (0.12)          | 27.6            | 12.2 / 14.9 / 65                  | 47.3 / 58.6                     | 0 / 0                    |
| 4   | bash  | 18.99 (0.60)         | 3.87                 | 42.9            | 84.1 / 97.2 / 229                 | 120.1 / 137.8                   | 0 / 0                    |
| 8   | relay | 2.43 (0.08)          | 7.76 (0.24)          | 28.0            | 34.2 / 56.3 / 124                 | 47.7 / 54.8                     | 0 / 0                    |
| 8   | bash  | 39.59 (1.24)         | 8.07 (0.25)          | 75.7            | 106.8 / 151.8 / 331               | 125.8 / 157.6                   | 0 / 0                    |
| 16  | relay | 4.98 (0.16)          | 17.03 (0.53)         | 51.4            | 40.5 / 62.9 / 310                 | 52.6 / 60.8                     | 0 / 0                    |
| 16  | bash  | 87.14 (2.73)         | 22.22 (0.70)         | 184.5           | 1171.7 / 1467 / 1953              | 881.8 / 1162                    | 274 / 36                 |

How to read it:

- Client CPU grows linearly with N on both paths. Per session it is about 0.01 core on the relay and 0.17 core on the bash path.
- The bash run at 16 sessions took 72% of the host's eight cores, so its latency is the host's own CPU contention.
- On the relay path, the daemon's 17 CPU-s is now 3.4 times the client's 5 CPU-s.
- The relay path's latency rises with N even though the host is mostly idle. Status ticks queue behind PreToolUse chains in one GIL-bound process.

The in-process costs in section 3 reproduce the daemon figure: 237 PreToolUse × 49.5 ms + 480 status × 5.6 ms + 237 PostToolUse × 7.4 ms ≈ 16.2 CPU-s, against 16.7 measured after subtracting the idle baseline.

## 3. Where the daemon-side cost sits (in-process, `inproc.py`, 300 reps after 20 warm-ups)

Method:

1. Build a `DaemonController` from this repository's config exactly as `cmd_start` does. `defer_nonessential_startup=True` means no CLAUDE.md or asset writes; only the guard-index pre-warm runs.
2. Wrap every registered handler class's `matches()`/`handle()` in a timer.
3. Call `process_request()` with the same payloads. CPU is `process_time`, so the bounded-dispatch worker thread is included.

The daemon logs no per-handler timing. Its stats keep only `avg_processing_time_ms`, and `probe` reports a verdict, not timing. That is why I used the in-process harness. A cProfile of `process_request` sees only the main thread, because the chain runs in a worker thread. `handler_prof.py` therefore calls each handler's `matches()` directly.

| Event                | Wall ms median / p90 | CPU ms median | Sum of handler time | Largest handlers (ms per request)                                                                          |
| -------------------- | -------------------- | ------------- | ------------------- | ---------------------------------------------------------------------------------------------------------- |
| Status               | 6.3 / 13.7           | 5.6           | 6.7                 | multithread-indicator 3.0, usage-indicator 1.0, context-sidecar 0.7, daemon-stats 0.5                      |
| PreToolUse Bash      | 52.0 / 65.2          | 49.5          | 50.1                | **prevent-destructive-git 19.1**, project-containment 3.9, write-protected-paths 3.1, secret-file-read 3.0 |
| PreToolUse Edit      | 8.2 / 10.0           | 7.6           | 6.3                 | secret-file-read 2.6, sensitive-content 0.6                                                                |
| PreToolUse Write 4KB | 50.1 / 60.6          | 47.0          | 47.2                | **secret-file-read 40.6** (about 10 ms/KB, still N467), comment-changelog 1.2, sensitive-content 1.1       |
| PostToolUse Bash     | 7.8 / 9.5            | 7.4           | 6.1                 | plan-fact-check-feed 3.5 (matches+handle), eslint-on-write 1.1, lint-on-edit 1.0                           |

The front controller outside the chain is small. A main-thread profile puts it at about 1.5 ms per request: verdict-log append 0.4 ms, response-contract check 0.3 ms, plus pydantic and JSON. The cost is in the handlers.

PreToolUse Bash depends on the command shape (`handler_prof.py`, matches() medians summed over 86 handlers, in `hprof.json`):

| Command shape                    | Sum ms |
| -------------------------------- | ------ |
| `ls -la …`                       | 12.6   |
| `git status --short`             | 11.7   |
| `git commit -m '…'`              | 19.7   |
| `pytest … > out 2>&1`            | 25.4   |
| a 4-stage grep/awk/sort pipeline | 34.9   |
| `git log … && ls …`              | 40.5   |

These sums were taken while the earlier QA run was still loading the host, so read them as relative sizes.

- A further 11 to 19 handlers cost over 0.5 ms each. They re-tokenise the same command independently: project containment, write-protected paths, the secret-file guard, plan-number-helper and others.
- **`prevent-destructive-git`.**
  - What it costs: `matches()` runs `_match_reason`, which calls `_segment_matches` once for each of the 18 patterns. Each call recomputes `_scan_target(command)` from scratch (`command_position_argument_segments` → `command_position_view` → heredoc scan and `split_unquoted_spans`), which is 54 `split_unquoted_spans` calls and 970k `str.startswith` calls per command. The only prefilter is `"git" in command.lower()`, so any command that mentions git pays this, including a path containing `.git` or `github`.
  - Effect of the fix: parsing once per `_match_reason` call (patched in the measuring process only, `T3_MEMO=1`, no cross-call cache, `inproc-memo.json`) took PreToolUse Bash from **49.5 to 31.9 ms CPU** (52.0 to 33.4 ms wall). The other events were unchanged.

## 4. Rust candidates, ranked (cost test: Plan 00495's Rules 0 to 3)

Budget context:

- No single event is over 100 ms (Rule 0a).
- On the relay path, daemon CPU at 16 sessions is 53% of a core, well over the 10%-of-a-core background line (Rule 0c). The owner's many-sessions framing makes this the figure that matters.
- On the bash path, client CPU is 2.7 cores, so the default-on relay is the first-order win and is already delivered.

| Rank | Candidate                                                                                                         | Measured cost today                                                                                     | Realistic saving                                                                                                                                                  | Complexity / risk                                                                                                                                                                                                  | Verdict                                                                                                                                                      |
| ---- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | **Python:** `prevent-destructive-git` parses once per command, not once per pattern                               | 19 ms of 49.5 ms per git-mentioning PreToolUse Bash                                                     | **−17.6 ms CPU per such call (−36%), measured.** At 16 sessions that is about 4 of the daemon's 17 CPU-s.                                                         | Trivial and local; the handler's own tests cover it                                                                                                                                                                | Not Rust. Do first.                                                                                                                                          |
| 2    | **Python:** one shared per-request parse of the Bash command (segments and command-position view) for every guard | The remaining 31.9 ms is spread over 86 handlers, 11–19 of them over 0.5 ms, mostly re-tokenising       | Not measured. Upper bound: the tokenising share of containment, write-protected paths, the secret-file guard and plan-number-helper, about 10 ms by their timings | Moderate: a request-scoped cache keyed on the command string; the parser stays the SSoT                                                                                                                            | Not Rust. Do second, then re-measure.                                                                                                                        |
| 3    | **Forwarder (generated bash, policy-free):** compute `SCRIPT_DIR` after the relay guard                           | 4.3 ms client CPU per relay call                                                                        | **−2.1 ms CPU per call (−49%), measured.** At 16 sessions that is 0.16 → about 0.08 core of client CPU                                                            | One line in `forwarder_generator.py`, plus a regenerate                                                                                                                                                            | Free; do it.                                                                                                                                                 |
| 4    | Hooks configured to run the relay binary directly, with no bash forwarder                                         | 2.2 ms after rank 3; relay alone 0.8 ms                                                                 | −1.4 ms per call, about 0.03 core at 16 sessions                                                                                                                  | The guard's per-call checks (binary present, socket present, loud status line) would have to move into the relay. That conflicts with the open owner question on the safety-forwarder fallback.                    | Small. Only if the relay owns the loud failure anyway.                                                                                                       |
| 5    | Native shell tokeniser (`shell_segmentation`, `heredoc_operators`) called from Python                             | It is the hot primitive under ranks 1 and 2, roughly 20–30 ms per Bash call today                       | After ranks 1 and 2, probably a few ms per call. Not measured, and no speed-up factor is assumed.                                                                 | Needs PyO3 or another extension build, which breaks the relay's std-only, zero-crate rule. It is a second implementation of the security-relevant parse, and a divergence between the two would be a guard bypass. | Policy-free in principle, but fails Rule 2 until the Python memo has landed and been re-measured. Revisit only if PreToolUse Bash is still over about 20 ms. |
| 6    | Compiled status-line renderer                                                                                     | 5.6 ms daemon CPU per tick (multithread-indicator 3.0 ms is half of it), about 0.09 core at 16 sessions | At most about 0.09 core at 16 sessions. A Python fix to the multithread indicator, or a per-session render cache across 1 s ticks, takes most of it.              | High: 18 renderers, config, and the status cache would all be duplicated in Rust, and display logic changes often                                                                                                  | Fails Rule 3. Fix the indicator in Python.                                                                                                                   |
| 7    | Native front controller for no-op paths                                                                           | The front controller outside handlers is about 1.5 ms per request                                       | Under 1.5 ms. Every Bash call has advisory handlers, so a native "nothing can match" skip is not available without compiling the policy.                          | Rule 1                                                                                                                                                                                                             | No case.                                                                                                                                                     |
| 8    | Secret-file guard content scan                                                                                    | 40.6 ms for a 4 KB Write (about 10 ms/KB); N465's prefilter does not stop it for ordinary code          | Large, but the residual is algorithmic                                                                                                                            | It is a guard, so Rule 1 applies                                                                                                                                                                                   | Python (ledger N467), as the 00495 assessment already found. These numbers show it is still open and matters for every Write over about 2 KB.                |

Bottom line for the owner:

- None of the further Rust candidates passes the cost test today.
- Default-on relay is the decisive change: client CPU per hot call goes from 80 to 4.5 ms, and 16 sessions stop saturating the host.
- The next gains are Python-side, in the PreToolUse Bash handler chain (ranks 1 and 2) and the Write content scan (rank 8).
- Rank 3 is a one-line forwarder fix.
- After ranks 1 and 2, re-measure. If daemon CPU at 16 sessions is still over about 0.3 core, or PreToolUse Bash is still over about 20 ms, rank 5 (a native tokeniser) is the one Rust candidate with a plausible case.

## Limits and side effects

- The daemon CPU deltas in the bench and concurrency runs include other live sessions' traffic. The idle baseline is reported.
- In-process numbers exclude the socket accept, which is under 0.15 ms.
- The status payload pointed at a nonexistent transcript, so transcript-reading paths may cost more in a real session.
- Tool calls every 2 s per session is a busy-agent rate. At a lower rate, the daemon figures scale down proportionally.
- About 6,000 synthetic-marked verdict records with fake session ids were added to the live verdict log. The in-process controllers also appended theirs, all marked `manual-probe`.
- Reproduce with the scripts in `untracked/scratch/t3/` (`bench.py`, `floor.py`, `conc.py`, `inproc.py` \[`T3_MEMO=1` for the what-if\], `handler_prof.py`). Each script's docstring states its method.
