# Plan 00126: Fix container-detection conflation + status-line env indicator + memoisation audit

**Status**: In Progress
**Created**: 2026-06-13
**Owner**: Claude (Opus)
**Priority**: High (root cause is a correctness smell entangled with daemon enforcement)
**Type**: Bug fix (root-cause) + Feature + Performance audit
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (parallel investigation → synthesis → TDD)

## Overview

The user asked for a small status-line icon confirming desktop vs container.
Investigating it surfaced a **major underlying code smell** that this plan must
fix, not route around.

Three linked pieces of work, in priority order:

1. **Root cause — container detection is built on tautological signals.** This
   daemon ONLY ever runs as a Claude Code hook, so `CLAUDECODE=1` and
   `CLAUDE_CODE_ENTRYPOINT=cli` are ALWAYS true in production. The container
   "confidence scorer" awards them 3 points each — and the container threshold
   is 3 — so the detector classifies every Claude Code session (desktop
   included) as a container. The signals meant to detect "container" actually
   detect "are we running under Claude Code," which is a constant. Must be
   fixed at the root.

2. **Environment indicator (the requested feature).** A status-line segment
   showing a precise icon: desktop (💻) vs container (🐳 docker / 📦 podman),
   built on the corrected, memoised detector.

3. **Memoisation audit.** The status line renders on every Claude Code refresh.
   Lifetime-invariant facts (environment, repo name, etc.) must be computed ONCE
   by the daemon and cached; status handlers only read cheap cached values.
   Audit every status-line handler for needless per-render work.

## Critical Finding — EMPIRICAL PROOF (drives the whole plan)

Measured live in a hooks-daemon hook environment:

```
CLAUDECODE=1
CLAUDE_CODE_ENTRYPOINT=cli
get_container_confidence_score() = 13
is_container_environment()       = True
indicators = [CLAUDECODE=1, CLAUDE_CODE_ENTRYPOINT=cli, DEVCONTAINER=true,
              IS_SANDBOX=1, container=podman, root UID 0]
```

`CLAUDECODE=1` alone scores **3 == threshold**. So a DESKTOP Claude Code session
(zero real container markers) scores `CLAUDECODE=1`(3) + `ENTRYPOINT=cli`(3) = 6
≥ 3 → mis-classified as a container.

**The conflation mixes three orthogonal facts under one "container" label:**

| Real fact                 | Honest signals                                            | Currently (mis)used as "container" |
| ------------------------- | --------------------------------------------------------- | ---------------------------------- |
| Running under Claude Code | `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`                    | YES (always true → tautological)   |
| YOLO / sandbox mode       | `IS_SANDBOX`, `/workspace`+`.claude/`, root UID           | YES                                |
| Actually in a container   | `/run/.containerenv`, `/.dockerenv`, `container=`, cgroup | YES (the only honest ones)         |

### Blast radius — call sites of the conflated detector

- `daemon/init_config.py` — auto-enables `enforce_single_daemon_process` "if
  container detected". On desktop this is TRUE → enforcement enabled on desktop.
- `daemon/enforcement.py` — `is_container_environment()` selects the aggressive
  SIGTERM "container" branch vs conservative PID-file cleanup. On desktop the
  aggressive branch likely runs (project-root-scoped, so bounded, but it is
  container-only behaviour executing on desktop).
- `handlers/.../yolo_container_detection` — the handler name itself fuses "yolo"
  and "container"; needs review for which fact it actually wants.

This is directly entangled with the v3.18.x–v3.19.x daemon-isolation work.

## Goals

- Replace "container" detection with a **precise** OS-level container-runtime
  detector (docker / podman / generic / none) using only honest container
  markers — mirroring the Plan 00125 `_uv_in_container` bash helper. Memoise it
  (daemon-lifetime invariant).
- Cleanly SEPARATE the orthogonal "running under Claude Code" and "YOLO/sandbox"
  concepts from "container" — name them for what they are; stop scoring
  tautological signals as container evidence.
- Re-point `init_config.py` / `enforcement.py` at the correct fact (precise
  container detection) so desktop sessions are not treated as containers.
- Add the requested status-line environment indicator on top of the corrected
  detector, fully memoised.
- Audit + fix needless per-render work across status-line handlers.

## Non-Goals

- Rewriting the status-line dispatch pipeline wholesale.
- Removing the legitimate YOLO/sandbox detection capability — it stays, but as
  its own clearly-named concept, decoupled from "container".

## Phase 1: Investigation (parallel sub-agents → reports in THIS folder)

- [ ] **Agent A — status-line per-render cost audit** → `status-line-audit.md`
  For every status_line handler: what work does `handle()` do per render
  (subprocess / file I/O / network / heavy compute)? Cached or recomputed?
  Classify each OK / should-memoise / expensive. Quote `file:line`.
- [ ] **Agent B — caching infrastructure & status dispatch frequency** → `caching-infra-review.md`
  How is the Status event dispatched and how often does Claude Code call the
  statusline command? What caching primitives exist (`ProjectContext`
  startup cache, `functools.lru_cache`, `stats_cache_reader`, TTL caches)?
  Recommend the standard memoisation pattern for daemon-lifetime invariants.
- [ ] **Agent C — container-detection conflation: full call-site + redesign** → `container-detection-review.md`
  Map every use of `get_container_confidence_score` / `is_container_environment`
  / `get_detected_indicators` / `yolo_container_detection`. For each, what
  fact does the caller ACTUALLY need (Claude Code? YOLO? container?)? Design
  the precise container-runtime detector + the clean separation, and assess
  the desktop-false-positive severity in enforcement/init_config.

## Phase 1 Findings (synthesis of the three agent reports)

**Container-detection conflation (`container-detection-review.md`):**

- Confirmed tautology; the scorer is also **duplicated verbatim** in the
  `yolo_container_detection` handler (DRY violation).
- Call sites & desktop bugs:
  - `init_config.py` `_get_enforcement_line` — **HIGH**: writes
    `enforce_single_daemon_process: true` into the user's *tracked*
    `hooks-daemon.yaml` on a desktop `init`; wrong default persisted and
    inherited by teammates.
  - `enforcement.py:49` — **MEDIUM**: aggressive SIGTERM→SIGKILL branch selected
    on desktop (bounded by the default-off `enabled` gate + project-root-scoped
    kill, but still container-only behaviour on desktop).
  - `yolo_container_detection` handler — **LOW–MED**: injects a false advisory
    every desktop session (advisory-only).
- Proposed honest `detect_container_runtime() -> "docker"|"podman"|"generic"|None`
  using only `container` env + `/run/.containerenv` + `/.dockerenv` (+optional
  `/proc/1/cgroup`), mirroring `venv.sh:_uv_in_container`.

**Caching infra (`caching-infra-review.md`):**

- Status renders re-run ALL ~10 status handlers in-process every refresh (hot path).
- `ProjectContext` (frozen-dataclass classmethod singleton, startup-computed) is
  the ESTABLISHED pattern and is already read on the Status path by
  `git_repo_name`. No `functools.lru_cache`/`cached_property` exists in `src/`.
- Recommendation: store the environment fact as a `ProjectContext`-style
  startup-computed attribute (extend `ProjectContext` or a sibling
  `EnvironmentContext` singleton) — NOT lru_cache.

**Status-line per-render cost (`status-line-audit.md`):**

- `git_branch` — **EXPENSIVE**: ~4 git subprocesses per render; calls 1&2
  redundant (toplevel known at startup; branch is in porcelain output); coalesce
  behind a 1–2s TTL.
- `model_context` + `thinking_mode` — **SHOULD-MEMOISE**: both parse the SAME
  `~/.claude/settings.json` every render; share one mtime-keyed reader.
- `account_display` — re-reads/regexes `.last-launch.conf` every render.
- `daemon_stats` — procfs RSS (psutil) + `version_check_cache.json` every render.
- Correctly NOT cached: `current_time` (live), `git_repo_name` (already cached —
  the model to copy), `working_directory` (pure compute).

## Phase 2: Decisions

- **D1 Memoisation mechanism:** follow the `ProjectContext` pattern (startup-
  computed cached attribute) for the environment fact; status handler does a pure
  read. The detector function itself is pure/invariant so additionally memoised.
- **D2 Concept split:** introduce three clearly-named predicates and stop scoring
  tautological signals as "container":
  - `running_under_claude_code()` — `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT`
  - `is_yolo_sandbox()` — `IS_SANDBOX` / `/workspace`+`.claude/` / root UID
  - `detect_container_runtime()` / `in_container()` — honest container markers only
    Re-point `init_config.py` + `enforcement.py` at `in_container()`. Keep the
    `yolo_container_detection` config key stable for backward compat.
- **D3 Icon mapping:** desktop 💻 · docker 🐳 · podman 📦 · generic container 📦.
- **D4 Scope/sequencing:** PENDING USER DECISION (see below) — split the
  safety-critical root fix from the status-icon + perf polish, or do it all in
  one plan.

## Phase 3: TDD Implementation

- [ ] Precise, memoised container-runtime detector (+ tests)
- [ ] Decouple YOLO/sandbox detection from container detection (+ tests)
- [ ] Re-point `init_config.py` + `enforcement.py` at precise detection (+ tests proving desktop is NOT treated as container)
- [ ] `environment_indicator` status-line handler (+ tests)
- [ ] Register handler (HandlerID, Priority, tag, `__init__`, config)
- [ ] Apply memoisation fixes the audit flags

## Phase 4: Verify

- [ ] Full QA `./scripts/qa/llm_qa.py all`
- [ ] Daemon restart RUNNING; icon correct in live status line
- [ ] Confirm enforcement/init no longer treat a desktop session as a container

## Success Criteria

- [ ] Container detection uses only honest container markers; no tautological
  Claude Code signals counted as container evidence
- [ ] Desktop Claude Code session is NOT classified as a container anywhere
- [ ] Status line shows the correct icon; detection runs once per daemon lifetime
- [ ] Audit report committed; needless per-render work memoised
- [ ] All QA passes

## Notes & Updates

### 2026-06-13

- Requested by user after the v3.19.x venv-isolation work.
- User flagged (correctly) that scoring `CLAUDECODE=1` as a container signal is
  nonsensical for a Claude-Code-only daemon, and demanded the plan tackle this
  root smell — not just the status icon. Empirical proof captured above.
- Memoisation is a hard constraint: no per-render work in the status line.
