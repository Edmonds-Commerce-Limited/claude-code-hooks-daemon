# Container Detection Review — Tautological Signals

**Scope**: `src/claude_code_hooks_daemon/utils/container_detection.py` and every consumer.
**Verdict**: Confirmed code smell. The "container" detector conflates three orthogonal facts and mis-classifies *every desktop Claude Code session* as a container. Read-only review — no source modified.

---

## 1. The Three-Facts Mapping

The detector (`get_container_confidence_score`, lines 20–85) sums points across signals that actually belong to three independent questions:

- **(a) Running under Claude Code** — always true for this daemon; it only ever runs as a Claude Code hook.
- **(b) YOLO / sandbox / unattended mode** — Claude Code's permission-bypass / sandbox posture.
- **(c) Actually inside an OS container** — Docker/Podman/OCI runtime.

| Signal (file:line)                                          | Points | Fact it *actually* speaks to                                                | Honest?                                                                                               |
| ----------------------------------------------------------- | ------ | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `CLAUDECODE == "1"` (`container_detection.py:36`)           | 3      | (a) running under Claude Code                                               | **Tautology** — always set by Claude Code CLI                                                         |
| `CLAUDE_CODE_ENTRYPOINT == "cli"` (`:39`)                   | 3      | (a) running under Claude Code                                               | **Tautology** — always `cli` for hook runs                                                            |
| `project_root == /workspace` + `.claude/` exists (`:44–45`) | 3      | (c)-ish — a *convention* of this project's containers, not a container fact | Weak proxy; false on any container not using `/workspace`, true on a desktop checkout at `/workspace` |
| `DEVCONTAINER == "true"` (`:52`)                            | 2      | (c) container (devcontainer)                                                | Honest-ish (devcontainer specific)                                                                    |
| `IS_SANDBOX == "1"` (`:55`)                                 | 2      | (b) YOLO/sandbox mode                                                       | Honest for (b), **not** (c)                                                                           |
| `container in {podman,docker}` (`:58–59`)                   | 2      | (c) container runtime                                                       | **Honest** — the real marker                                                                          |
| socket file present (`:64`)                                 | 1      | nothing useful — true whenever the daemon ran before                        | Noise                                                                                                 |
| `os.getuid() == 0` (`:72`)                                  | 1      | weak (c) hint — but root is normal on many desktops/CI                      | Noise                                                                                                 |

`is_container_environment(threshold=3)` (`:88–102`) returns `score >= 3`.

### Desktop false-positive arithmetic (confirmed)

On a **desktop Claude Code session** (macOS/Linux laptop, no container):

- `CLAUDECODE=1` → **+3** (always present)
- `CLAUDE_CODE_ENTRYPOINT=cli` → **+3** (always present)

Score = **6 ≥ 3** → `is_container_environment()` returns **True** before any genuine container marker (`container=…`, `/.dockerenv`, `/run/.containerenv`) is even consulted. Either tautological signal *alone* (+3) already meets the threshold. **A desktop session is unconditionally classified as a container.** The two genuine secondary/tertiary container markers contribute nothing to the outcome because the gate is already satisfied by facts that are true everywhere.

The tautology is doubly entrenched: the same scoring logic is **duplicated verbatim** inside the handler (`yolo_container_detection.py:69–129` `_calculate_confidence_score`), so the smell exists in two places (DRY violation).

---

## 2. Call-Site Analysis

Three consumers. Quotes are `file:line`.

### Site A — `daemon/init_config.py:19` (`_get_enforcement_line`)

```python
in_container = is_container_environment()              # init_config.py:19
if in_container:
    return "  enforce_single_daemon_process: true   # Auto-enabled (container detected)\n"   # :21
```

- **Fact actually needed**: (c) real container — single-daemon enforcement is meant for containers/single-user machines, explicitly *not* shared multi-project hosts (per CLAUDE.md).
- **Desktop bug**: On a desktop `init`, `is_container_environment()` is `True`, so the generated `hooks-daemon.yaml` is written with `enforce_single_daemon_process: true`. The desktop user is silently opted into aggressive enforcement that the docs say is for containers only.
- **Severity**: **HIGH**. This is the worst site: it doesn't just mis-read at runtime, it **persists a wrong default into the user's tracked config file**. The bad value survives every subsequent start regardless of detection, and a teammate who clones the repo inherits it.

### Site B — `daemon/enforcement.py:49` (`enforce_single_daemon`)

```python
in_container = is_container_environment()              # enforcement.py:49
...
if in_container and other_daemons:                     # :63
    logger.warning("Container environment: Killing ... other daemon process(es)")
    for pid in other_daemons:
        kill_daemon_process(pid)                        # :69  (SIGTERM → SIGKILL)
elif not in_container:                                  # :75
    # conservative: only clean up stale PID file
```

- **Fact actually needed**: (c) real container — the aggressive SIGTERM/SIGKILL branch is justified only when PID namespaces make a system-wide kill safe-ish; on a multi-project desktop it is not.
- **Desktop bug**: `in_container` is `True` on every desktop, so a desktop daemon start takes the **aggressive kill branch** (`:63`) instead of the conservative PID-file cleanup (`:75`). It will SIGTERM→SIGKILL any sibling daemon it finds.
- **Severity**: **MEDIUM**, *bounded* by two guards: (1) `enforce_single_daemon` is a no-op unless `config.daemon.enforce_single_daemon_process` is enabled (`enforcement.py:42`, default `False` per `models.py:453–456`) — so damage only manifests when Site A's bad default (or a manual opt-in) is in effect; (2) `find_all_daemon_processes(project_root=...)` (`process_verification.py:48–103`) scopes kills to *this project's* daemon and never kills daemons whose root it cannot attribute (`:92–95`, fail-safe). So the realistic blast radius is "kill another daemon for the **same** project root" — which on a desktop is usually the intended single-instance behaviour anyway. The smell is that the *reason* it works is luck (scoping), not correct detection; the misclassification removes the desktop-safe conservative path entirely.

### Site C — `handlers/session_start/yolo_container_detection.py` (advisory)

Uses its own duplicated scorer `_calculate_confidence_score` (`:69–129`) via `matches()` (`:238–240`, threshold 3), then `handle()` injects context (`:271–290`).

- **Fact actually needed**: (b) YOLO/sandbox — the handler's *purpose* is to tell Claude it's in a YOLO sandbox ("running as root, ephemeral storage, no permission prompts").
- **Desktop bug**: On every desktop session the handler **fires** (score 6 ≥ 3) and injects a false "🐳 Running in YOLO container environment … Running as root - install packages freely … Storage is ephemeral" banner (`:272`, `:287–290`) into a non-container desktop session. The advice is actively wrong (storage isn't ephemeral; the user isn't root; permission prompts *are* active).
- **Severity**: **LOW–MEDIUM**. Advisory only (never blocks; `terminal=False`), but it's misinformation injected into the model's context on every desktop session and erodes trust in advisory output (cf. memory note on advisory-channel stickiness). No data-loss risk.

### Call-site table

| Site (file:line)                                   | Fact needed        | Desktop bug today                                                                                                                        | Severity       |
| -------------------------------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `init_config.py:19` `_get_enforcement_line`        | (c) real container | Writes `enforce_single_daemon_process: true` into the user's persisted config on desktop `init`                                          | **HIGH**       |
| `enforcement.py:49` `enforce_single_daemon`        | (c) real container | Takes aggressive SIGTERM→SIGKILL branch on desktop instead of conservative PID cleanup; bounded by `enabled` gate + project-root scoping | **MEDIUM**     |
| `yolo_container_detection.py:238` (own dup scorer) | (b) YOLO/sandbox   | Injects false "YOLO container / root / ephemeral" advisory into every desktop session                                                    | **LOW–MEDIUM** |

---

## 3. Precise Container-Runtime Detector (design)

A single honest detector that answers **only** fact (c), mirroring the bash helper `_uv_in_container` (`scripts/install/venv.sh:431–444`) for parity.

### Signature

```python
ContainerRuntime = Literal["docker", "podman", "generic"]

def detect_container_runtime() -> ContainerRuntime | None:
    """Return the detected OS container runtime, or None when not in a container.

    Uses ONLY honest container markers. Does NOT consider CLAUDECODE,
    CLAUDE_CODE_ENTRYPOINT, IS_SANDBOX, project root, socket files, or UID —
    none of those are container facts.
    """

def is_in_container() -> bool:
    """True iff detect_container_runtime() is not None."""
    return detect_container_runtime() is not None
```

### Signals and precedence (most specific first; mirrors `_uv_in_container`)

1. **`container` env var** → maps the value directly:
   - `"podman"` → `"podman"`, `"docker"` → `"docker"`, `"oci"`/`"crio"`/anything else truthy → `"generic"`.
     (Bash parity: `venv.sh:432–436` matches `podman|docker|oci|crio`.)
2. **`/run/.containerenv`** exists → `"podman"` (Podman's marker; overridable via `HOOKS_DAEMON_CONTAINERENV_PATH` for test parity with `venv.sh:437`).
3. **`/.dockerenv`** exists → `"docker"` (overridable via `HOOKS_DAEMON_DOCKERENV_PATH`, parity with `venv.sh:440`).
4. *(optional, last resort)* **`/proc/1/cgroup`** contains `docker`/`kubepods`/`containerd`/`libpod` → `"generic"`. Mark as best-effort; skip on non-Linux (file absent). Not in the bash helper — include only if a marker-less container case is observed in the field, else honour YAGNI and omit.

If none match → `None`. **Explicitly excluded** (the tautology/noise removed): `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `/workspace`+`.claude/`, `IS_SANDBOX`, socket presence, `getuid()==0`.

Marker-file probes wrapped in `try/except OSError` returning the non-match path (fail-safe: unknown → not a container), consistent with the existing module's error posture.

### Memoisation (daemon-lifetime invariant)

Container membership cannot change within a single daemon process lifetime (you don't migrate a running process into/out of a container). Memoise once:

```python
from functools import cache

@cache
def detect_container_runtime() -> ContainerRuntime | None: ...
```

- `functools.cache` gives a process-lifetime singleton — computed on first call, reused thereafter; matches the "daemon-lifetime invariant" requirement.
- **Test seam**: marker paths read via the `HOOKS_DAEMON_CONTAINERENV_PATH` / `HOOKS_DAEMON_DOCKERENV_PATH` overrides (parity with `venv.sh`), and tests must call `detect_container_runtime.cache_clear()` in setup/teardown to re-evaluate per env permutation. Env vars are read *inside* the function (not at import) so the cache is the only state.

---

## 4. Concept Separation & Migration

The clean design splits the one conflated function into three clearly-named concepts, each answering exactly one fact:

| Concept                   | Fact | Proposed home / name                                                                                                                | Signals                                                                          |
| ------------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Running under Claude Code | (a)  | `utils/claude_code_env.py::is_running_under_claude_code()`                                                                          | `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` — *informational only; never a gate*      |
| YOLO / sandbox mode       | (b)  | `utils/sandbox_detection.py::is_yolo_sandbox()` (or reuse `permission_mode == "bypassPermissions"` from hook input where available) | `IS_SANDBOX`, plus Claude Code's `permission_mode` when a handler has hook_input |
| Real container runtime    | (c)  | `utils/container_detection.py::detect_container_runtime()` / `is_in_container()`                                                    | honest markers from §3                                                           |

### Re-point each call site to the fact it needs

- **Site A** `init_config.py:19` → `is_in_container()` (fact c). Desktop now correctly leaves `enforce_single_daemon_process` commented/`false`.
- **Site B** `enforcement.py:49` → `is_in_container()` (fact c). Desktop takes the conservative branch again.
- **Site C** `yolo_container_detection.py` → drive `matches()` off fact (b) `is_yolo_sandbox()` (optionally AND fact c for the "🐳 container" wording). Delete the duplicated `_calculate_confidence_score` / `_get_detected_indicators` scorers (DRY). Rename concept if desired, but the handler's *config key* `yolo_container_detection` should stay (see compat).

### Backward-compatibility concerns

The public API is imported by production code **and** tests:

- **Production importers**: `enforcement.py:18`, `init_config.py:9` (both `is_container_environment`). Update these to the new function in the same change.
- **Test importers** (must not break silently):
  - `tests/unit/utils/test_container_detection.py:12–15` imports all three: `get_container_confidence_score`, `get_detected_indicators`, `is_container_environment` — these tests *encode the tautology* (they assert the +3 scoring). They must be **rewritten** to the new marker-based contract, not patched to keep passing (per memory: never weaken tests to match code — but here the old tests assert *wrong* behaviour, so they are replaced as part of the behaviour change).
  - `tests/unit/daemon/test_init_config.py` and `test_enforcement.py` patch `...init_config.is_container_environment` / the enforcement import by **module path** — update the patch targets to the new name.
  - `tests/unit/handlers/session_start/test_yolo_container_detection.py` exercises the handler's own scorer — rewrite for fact (b).
- **Migration options**:
  1. **Preferred (clean break)**: rename to `is_in_container()` / `detect_container_runtime()`, update all 2 production sites + tests in one commit. The module has no external public consumers (it's daemon-internal `src/`), so no deprecation window is required.
  2. **Soft**: keep `is_container_environment()` as a thin alias `= is_in_container` for one release with a deprecation note, to de-risk any out-of-tree importer. Given this is upstream-internal code, option 1 is cleaner and YAGNI-aligned; reserve option 2 only if external plugins are known to import it (none found).
- **Config-key stability**: the handler's YAML key `yolo_container_detection` (`constants/handlers.py:286,542`; `init_config.py:214`) and `HandlerID.YOLO_CONTAINER_DETECTION` should remain unchanged to avoid breaking existing user configs — only the *internal detection logic* changes, not the public handler identity.

---

## Summary (6 lines)

1. Confirmed: `get_container_confidence_score` awards 3+3 for `CLAUDECODE=1` and `CLAUDE_CODE_ENTRYPOINT=cli` (always true under Claude Code), so a desktop session scores ≥6 ≥ threshold 3 and is unconditionally mis-classified as a container — fact (a) is conflated with fact (c).
2. Three consumers, all needing the real-container fact (c) or the YOLO fact (b), get the tautological answer instead.
3. **Worst call-site bug**: `init_config.py:19` `_get_enforcement_line` writes `enforce_single_daemon_process: true` into the user's *persisted* `hooks-daemon.yaml` on a desktop `init` — **severity HIGH** (a wrong default is committed to tracked config and inherited by teammates).
4. `enforcement.py:49` takes the aggressive SIGTERM→SIGKILL branch on desktop (severity MEDIUM, bounded by the default-off `enabled` gate and project-root-scoped kill in `process_verification.py:92–95`).
5. `yolo_container_detection.py` injects a false "YOLO/root/ephemeral" advisory into every desktop session (severity LOW–MEDIUM, advisory-only).
6. Fix: an honest `detect_container_runtime() -> "docker"|"podman"|"generic"|None` using only `container` env + `/run/.containerenv` + `/.dockerenv` (+optional `/proc/1/cgroup`), `@cache`-memoised for the daemon lifetime, mirroring `venv.sh:_uv_in_container`; split (a)/(b)/(c) into separately-named concepts and re-point all three sites; rewrite the tautology-encoding tests and keep the `yolo_container_detection` config key stable for backward compat.
