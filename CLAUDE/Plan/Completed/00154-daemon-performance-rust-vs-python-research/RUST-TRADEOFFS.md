# Plan 00154 — Rust Options: Honest Tradeoff Analysis

Evaluates the three Rust variants the maintainer asked about, plus the one variant the measurements actually point at. Upside numbers derive from the measurements in [RESEARCH.md](RESEARCH.md) §4; costs are stated plainly, including the transparency cost the maintainer asked not to be glossed.

**Baseline to beat**: typical hook event ~45 ms end-to-end, of which the entire Python daemon side is **1.8 ms**; 1 MB Write 114 ms end-to-end, of which scanners ~40 ms; status render ~64 ms, ~76% client-side spawn. After the free tuning in [PYTHON-TUNING.md](PYTHON-TUNING.md) (T1-T4), the typical event is ~20-23 ms with the daemon side ~0.4 ms.

---

## Option A — Full Rust rewrite (socket server + dispatch + handlers)

**Upside (measured ceiling)**: the daemon side of a typical event is 1.8 ms (0.4 ms post-T1). A perfect Rust daemon at 0 ms saves **≤ 2 ms of a 45 ms path (≤ 4%)** — invisible against the budget in RESEARCH.md §5. Memory: RSS 51 MB → ~5-15 MB (*estimate*), worth ~40 MB per open project. CPU: < 2 s/hour → ~0. Cold start 1.26 s → ~10 ms (*estimate*) — but cold start happens once per session.

**Costs**:

- **Transparency — total loss.** 57,702 LOC of policy-bearing Python (97 handlers, 72 strategies) become a compiled blob. See §5 below; this is the deal-breaker stated plainly.
- **Rewrite scale**: 97 handlers + 72 language strategies + config/plugins/plan-QA/CLI. Years of accreted edge-case behaviour (Plan 00127 socket-liveness dance, hostname isolation, self-install mode…) to re-verify.
- **Extensibility break**: project-level handlers (`.claude/project-handlers/`) and plugins are *Python by contract*. A Rust daemon must either embed CPython (then why rewrite?) or break the public extension API.
- **Distribution**: per-platform binaries (linux x86_64/aarch64, macOS x86_64/arm64 at minimum), signing/checksums, a much heavier release pipeline than today's already-strict one.

**Verdict**: never. The measured upside rounds to zero where it matters.

## Option B — PyO3 hybrid (Rust core: socket/JSON/routing; Python handlers)

**Upside (measured ceiling)**: the stages a Rust core would own are the socket floor (0.12 ms), JSON (5-40 µs typical), pydantic (~4 µs), routing/chain overhead (~30 µs ex-T1). Combined: **< 0.5 ms per typical event, ~1% of end-to-end**. The GIL still serialises the Python handlers, so no concurrency win either.

A sub-variant with real upside: **Rust regex scanning behind the existing strategy Protocol** (the actual hotspot — 74% of daemon CPU, ~48 µs/KB). Rust `regex` crate does streaming alternation cheaply; *estimate* 5-20× → 1 MB write scan 40 ms → 2-8 ms. But: this only matters for ≥ 100 KB writes (rare), and T5's pure-Python single-pass work gets an estimated 2-5× first. Pattern *data* could stay introspectable (patterns remain declarative tables; only the match engine compiles), so the transparency cost here is genuinely low — the engine is policy-free, the patterns are the policy.

**Costs**: build toolchain (maturin/abi3 wheels per platform × Python version), a second language in the QA pipeline (today: black/ruff/mypy/pytest/bandit — none speak Rust), debugging across the FFI boundary, and the precedent that "some of the daemon is compiled now".

**Verdict**: not now. The core hybrid is measurably pointless; the scanner extension is the only defensible PyO3 target and is dominated by T5 until someone demonstrates routine multi-MB writes.

## Option C — Compiled transport forwarder (the option the data actually points at)

Not on the original list, but honesty requires naming it: **95% of typical-path cost is the client-side spawn stack, not the daemon**. A single small static binary (Rust, ~200-400 LOC: read stdin → wrap `{"event":…,"hook_input":…}` → AF_UNIX round-trip → print/translate exit code) replaces `bash + init.sh + jq + python3` per event.

**Upside (from measured floors)**: typical event 45 ms → **~3-5 ms** (spawn of one small static binary ≈ 1-2 ms); status render 64 ms → ~18 ms (daemon-side git forks then dominate → with T4, ~8 ms). This is 10-20× on the real end-to-end number — the only Rust option whose win is larger than its rounding error.

**Costs**:

- **Transparency: low but not zero.** The forwarder carries *no policy* — every block/allow decision stays in readable Python. But the daemon-startup/fallback logic in `init.sh` (venv resolution, CI passthrough, not-installed messaging) would partly move into the binary; users could no longer read *the transport's* error handling as shell. Mitigable by keeping the binary dumb (transport only) and falling back to the bash path when the binary is absent.
- **Distribution & supply chain: the real price.** 4+ platform binaries in every release, sha256 manifests (the release pipeline already does this for scripts), reproducible builds if trust matters, and a Rust toolchain in CI. For a safety project whose pitch is auditability, shipping *any* opaque executable to client repos is a posture change that needs deliberate sign-off.
- **Edge-case re-verification**: init.sh's accreted behaviours (hostname suffix agreement with paths.py, socket-discovery file, passthrough modes) must be replicated bit-for-bit or deliberately left to the bash fallback.

**Verdict**: the only Rust increment worth ever doing — *after* T2/T3 land and only if the residual ~20 ms/event is still judged to matter. See [RECOMMENDATION.md](RECOMMENDATION.md).

## Option D — Status quo + Python tuning (control case)

T1-T4 (no Rust, no new deps): typical event ~20-23 ms, status render ~25-30 ms, daemon-side Bash event 0.4 ms. Retains 100% source transparency, zero build/distribution change. This is the bar every Rust option must beat *on evidence*.

---

## 5. The transparency cost, stated plainly

This project's core value proposition is **trusted interception**: it blocks agent actions and injects guidance, in client repos, with root-adjacent reach over a developer's workflow. Today that trust is auditable in four concrete mechanisms, all of which assume readable Python:

1. **Agents and humans read handler source.** A blocked agent (or suspicious human) can `Read` the exact `matches()`/`handle()` that denied it and see there is no hidden behaviour. In-context, this happens routinely — deny messages cite handler and config key.
2. **Documentation is *generated from* the source.** `get_claude_md()` returns the guidance injected into CLAUDE.md; `generate-docs` and the acceptance playbook derive from handler code. Compiled handlers sever the guarantee that documented behaviour == actual behaviour.
3. **The extension API is the same class users read.** Project handlers subclass the identical `Handler` ABC; the built-ins are the reference implementations. Compile the built-ins and the reference library goes dark.
4. **Debugging is grep-and-read.** The dogfooding workflow (restart, probe with `nc`, read the handler) dies at an FFI boundary.

A Rust daemon (Options A, and partially B) converts "you can verify what this hook does in 30 seconds" into "trust our build pipeline". For a tool whose competitors are `settings.json` one-liners a user can read at a glance, that is a real product regression, not a sentimental one. **The honest hierarchy**: policy code (handlers/strategies) must stay readable; policy *data* (regex tables) may be compiled against with low cost; policy-free transport (Option C) is the only layer where compilation costs little transparency — and it happens to be the only layer where compilation buys real performance.

## 6. Quantified side-by-side

| Option                         | Typical event (45 ms) | 1 MB write (114 ms) | Status render (64 ms) | RSS (51 MB) | Transparency cost | Build/distribution cost | Effort        |
| ------------------------------ | --------------------- | ------------------- | --------------------- | ----------- | ----------------- | ----------------------- | ------------- |
| D: Python tuning T1-T4         | ~20-23 ms             | ~90 ms              | ~25-30 ms             | 51 MB       | none              | none                    | days          |
| + T5 scanner single-pass       | ~20-23 ms             | ~60-80 ms (est.)    | ~25-30 ms             | 51 MB       | none              | none                    | ~1-2 wks      |
| C: compiled forwarder (post-D) | **~3-5 ms**           | ~50-60 ms (est.)    | ~8-18 ms              | 51 MB       | low (transport)   | high (4+ platform bins) | wks + ongoing |
| B: PyO3 scanner engine         | ~20-23 ms             | ~25-30 ms (est.)    | ~25-30 ms             | ~55 MB      | low-medium        | high (wheels matrix)    | wks + ongoing |
| B: PyO3 core hybrid            | ~19-22 ms             | ~85 ms              | ~24-29 ms             | ~40 MB est. | medium            | high                    | months        |
| A: full Rust rewrite           | ~3-5 ms\*             | ~10 ms (est.)       | ~8 ms (est.)          | ~5-15 MB    | **total**         | very high               | year+         |

\* Option A only reaches ~3-5 ms if it *also* replaces the forwarder (i.e. includes Option C); a Rust daemon behind the current bash forwarder stays at ~43 ms.

Rows marked *est.* were not prototyped; the D and C latency figures are arithmetic on measured stage costs (RESEARCH.md §4.1-4.4).
