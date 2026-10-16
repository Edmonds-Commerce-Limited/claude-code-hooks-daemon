# Rust helpers for hot paths: assessment for the owner

Plan 00495 Task 3.2. The owner's question (ruling A3): no full rewrite is on the table; do particular heavy paths
justify a native helper? This document answers it from the numbers measured in Phase 1, Phase 2 and the Task 1.4
re-measurement ([BASELINE.md](../../../Performance/BASELINE.md), section "Plan 00495 re-measurement"). The decision is the
owner's; the follow-up plan filed with this document puts it to them.

## Verdict

**No path justifies a new native helper today.** One path is badly heavy, but it is heavy because of how the Python is
written, and a Python change (ledger N465, fixed separately) removes the cost without a second toolchain. The one native helper that was ever justified
(the transport relay) already exists. Details per path follow, then the cost of a helper, then what the owner is asked.

## The rules this is judged by

From [Performance/README.md](../../../Performance/README.md), Plan 00154's decision framework:

- Rule 0: a cost matters only above a budget (a single event over about 100 ms p95, hook overhead over about 1% of a tool
  turn, or background CPU over 10% of a core).
- Rule 1: never compile policy. Handlers and strategies stay readable Python.
- Rule 2: compile only policy-free layers, only on evidence, only after the free Python win has landed.
- Rule 3: quantify both sides; a small saving loses to the distribution cost automatically.

## Paths that stay heavy, and what a native helper would save

| Path                                          | Cost now (measured)                                                                      | Upper bound a native helper could save                        | Policy in it?                         | Verdict                                                         |
| --------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------- |
| Secret-file guard scanning Write/Edit content | 1208 ms per 115 KB Write (about 9 ms/KB, linear); 9.3 s for 1.15 MB; 102 ms at 11.5 KB   | all of it, but a Python prefilter takes the same cost away    | yes (what counts as a protected path) | Not a Rust candidate: Python fix, ledger N465, fixed separately |
| Other content scanners (five handlers)        | 40 ms per 115 KB Write in all (0.04 to 0.10 ms/KB); about 0.35 s per MB                  | under 40 ms per 115 KB Write                                  | yes (the patterns are the policy)     | Below Rule 0; helper not justified                              |
| Handler-chain dispatch                        | 7.4 ms (47 handlers) to 10.2 ms (80 handlers) p50 per PreToolUse; 0.1 ms per `matches()` | at most the 7.7 ms of `matches()` calls, none of it hot       | yes, it IS the policy                 | Rule 1 forbids; a Python index by tool name is the lever        |
| Docs and plan QA sweeps                       | 5.9 CPU-s on a cache miss (docs 4.1, plan 1.75); 0.1 s on a hit; off the critical path   | up to 5.9 CPU-s per tree change, in the background            | yes (the checks are the policy)       | Rule 1 forbids; already off the critical path by Task 2.6       |
| Daemon start before the bind                  | 1.0 to 1.1 s CPU: import 0.40, config load and validation 0.46, handler build 0.11       | none from a helper: the cost is Python imports and validation | no                                    | Below budget (2 s); lazy imports are the Python lever           |
| Transport (the per-event process spawn)       | 34.1 ms p50 with the Python transport; 4.3 ms with the relay (Plan 00290)                | 29.8 ms per event, already taken when the relay is enabled    | no (policy-free by construction)      | Delivered, opt-in; whether to default it on is the owner's call |
| Status-line render                            | 15.75 ms daemon side, TTL-cached, asynchronous                                           | none that anyone waits for                                    | no                                    | No case                                                         |

### 1. Secret-file guard on Write content (the heavy one)

`block-secret-file-read` (`utils/secret_file_matching.py`, `_shell_words`, through `utils/linear_shlex.py`) runs `shlex`
over every line of a Write or Edit's content, so the cost is linear in the size of the write and independent of what the
content says. Measured on this repository's config and on the shipped example config alike:

| Write size | Guard time (`matches()` alone) |
| ---------- | ------------------------------ |
| 11.5 KB    | 102 ms                         |
| 115 KB     | 1.17 s                         |
| 1.15 MB    | 9.3 s                          |

A cProfile of the 1.15 MB case spent 2.1 s of its 5.0 s in `linear_shlex.read_token` (375,000 tokens) and 0.4 s in
`str.translate`. This breaks Rule 0(a) for any Write over about 11 KB, and the other 79 handlers together add under 40 ms
to the same request, so the guard is the whole cost.

Why a helper is the wrong tool: the work is tokenising text that, in the usual case, mentions no protected path at all.
The Python lever is to establish cheaply that a protected path could not be in the content before tokenising it (a
substring or single compiled-alternation test over the content, microseconds), and to tokenise only content that passes.
That is a change inside the guard, covered by its existing tests and by new ones for the large-write case, and it needs no
second toolchain. A native tokeniser would run the same work faster, but the saving over the Python fix is nothing, since
the Python fix removes the work. This is a Python fix tracked as niggles ledger entry N465 and fixed separately from this
plan, so it is not a Rust candidate and the owner is not asked to decide it. The figures above are the cost before that
fix; this assessment does not measure the fix.

Auditability cost of doing it natively regardless: this is a security guard, so its policy would move into a compiled
file. That is exactly what Rule 1 exists to prevent.

### 2. The other content scanners

Security antipatterns 12.0 ms, sensitive content 11.1, error hiding 6.1, comment changelog 5.9 and comment size 5.0 ms for
a 115 KB Write: 40 ms in all, 0.35 s for a 1 MB Write. Writes of that size are rare, and 40 ms is under Rule 0(a). Even an
engine that cost nothing would save at most those 40 ms per large Write. A native regex engine would also need the `regex`
crate, which breaks the relay's constraint of std only and zero crates (the relay's single auditable file is what made a
compiled artefact acceptable at all). Rule 3 settles it.

### 3. Handler-chain dispatch

7.4 ms (47 handlers) to 10.2 ms (80 handlers) at p50, against 1.8 ms for 38 handlers in Plan 00154. That is a 4 to 5 times
growth, but the cost is spread: summing each handler's own `matches()` on the 80-handler chain gives 7.7 ms of an 8.9 ms
request, 0.1 ms each on average, the largest being 1.07 ms. There is nothing hot to replace, and the code in question is
the policy itself, which Rule 1 keeps in readable Python. The Python lever, if the owner wants it, is to skip handlers that
cannot apply to the event's tool name before calling `matches()`; it is not needed to meet Rule 0, because the event is
about 8 ms of a roughly 32 to 45 ms hook call and human-gated tool turns last seconds.

### 4. Docs and plan QA sweeps

On a cache miss: docs 4.1 CPU-s and plan 1.75 CPU-s (Phase 1), about 5 s on the SessionStart chain (Task 2.6). On a hit,
0.1 s. Task 2.6 moved them off the blocking chain and keyed them by a fingerprint, so a typical session start pays the
hit cost. A helper could in principle cut the miss, but the sweeps ARE the documentation and plan checks, which clients
read and extend; compiling them fails Rule 1, and the miss no longer blocks anything.

### 5. Daemon start

After Phase 2, 1.0 to 1.1 s CPU before the bind, of which importing the CLI is 0.40 s and loading and validating the config
0.46 s. Phase 1's profile attributed the import time to pydantic model builds (53 constructions) and about 960 `re.compile`
calls, and the validation to repeated name conversions (5,270 `_to_snake_case` calls). These are Python-level costs:
lazy imports, lazy compilation and a cached conversion would take them, and a native helper cannot, because the time is
spent inside the interpreter doing Python work. It is under the 2 s budget, and the status bar no longer waits on it
(Task 2.7). Remaining Python saving is plausibly a few tenths of a CPU-second; no case for anything beyond that.

### 6. Transport

The only evidence-backed helper, and already built: Plan 00290's `relay/hooks_relay.rs` (std only, zero crates, plain
`rustc` with the musl target, one auditable file; the binary is built from source and never committed). Measured then:
4.3 ms p50 against 34.1 ms for the Python transport on the same container. It is opt-in (`transport.relay_enabled`). Phase 2
did not touch it. The decision still open is whether it should be on by default, which turns on the distribution cost below.

## What a native helper costs (the auditability side)

For the relay this is already paid and known; any further helper pays it again:

- A second toolchain (`rustc`, the musl target) in the build and release path, and a binary per supported target.
- A supply-chain surface: a client either builds it or trusts a published binary. The relay keeps this small by being one
  file with no crates, which a reviewer can read in one sitting; a helper needing crates loses that.
- Policy must not enter it (Rule 1), so each helper has to be provably policy-free, which is a standing review burden.
- The Python fallback has to stay, so there are two implementations to keep equivalent, and a divergence between them is a
  security-relevant bug when the code in question is a guard.

## Recommendation

1. Do not commission a new native helper. None of the six paths passes Rule 3.
2. The secret-file guard's linear tokenising is the single path over the Rule 0 budget. It is a defect in an algorithm
   rather than a limit of the language, and it is in the guard class where an unexamined native rewrite is least wanted.
   It is a Python fix tracked as ledger N465 and fixed separately, so it is not put to the owner.
3. Leave the relay as it is (opt-in) unless the owner wants it default-on; that choice is about distribution, not speed.

## Method and limits

Figures are from [BASELINE.md](../../../Performance/BASELINE.md), measured on an 8-core Linux box at host load 3 to 13, so
absolute times are rough and the CPU-second figures are the dependable ones. Dispatch and scanner costs were measured
in-process (`process_request`, per-handler timers on `matches()`), not over a socket. No native code was written or
benchmarked for this assessment: every "saving" above is an upper bound taken from the measured cost of the Python path,
because a speed-up factor for a hypothetical helper would be a guess.
