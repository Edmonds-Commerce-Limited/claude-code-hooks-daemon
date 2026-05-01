# Plan 00104: v3.10.0 — venv resolver DRY + upgrade-flow resilience + production bug fixes

**Status**: Not Started
**Created**: 2026-04-30 (rewritten 2026-05-01 to absorb field-report issues)
**Owner**: TBD
**Priority**: High — contains active production bugs (issues #4 and #6 below) plus the structural DRY work that was previously deferred
**Recommended Executor**: Opus 4.6 (Sub-Agent Teams) — complexity warrants strategic oversight per three prior FATAL reviews of the original v1 attempt
**Execution Strategy**: Sub-Agent Teams with explicit commit-by-commit ordering and per-commit verification gates

## Why this plan now covers everything

The original 00104 was scoped to DRY consolidation only. The 2026-05-01 field
report (`context/2026-05-01-field-report-upgrade-issues.md`) surfaced six
additional production issues during a v2.26.0 → v3.9.1 upgrade attempt:

1. **Stale skill scripts** hardcoded the retired legacy venv path; the skill
   `upgrade.sh` runs whatever was deployed at install time rather than fetching
   latest from GitHub (architectural — same pattern as how `install.sh`
   bootstraps).
2. **`upgrade_version.sh` bootstrap paradox** — it requires a valid existing
   venv to find a Python interpreter, so jumping a major venv-format boundary
   leaves no entry point. Should fall back to `ensure_venv` to create one.
3. **Untracked `uv.lock` blocks `git checkout`** during version switching.
4. **`write-venv-metadata` stores the wrong `python_path`** in
   `.daemon-metadata.json` — it records the *system* Python that invoked the
   CLI rather than the venv's own `bin/python`. Skill scripts read this field
   via `paths.py resolve-venv` and end up running daemon code under
   `/usr/bin/python3.11`, which has no daemon packages installed →
   `ModuleNotFoundError: No module named 'claude_code_hooks_daemon'`. **This
   breaks `daemon-cli.sh` for every fresh install of v3.9.1.**
5. **`verify_venv` race on overlay-fs** — `sync -f` after `uv sync` with
   `UV_LINK_MODE=copy` is insufficient on Podman overlay-fs; `verify_venv`
   transiently fails despite the venv existing.
6. **`health-check.sh` ignores resolved `$PYTHON`** — sources `_resolve-venv.sh`
   correctly but a separate code path inside the script invokes the daemon CLI
   via a hardcoded interpreter, defeating resolution.

The user direction (2026-05-01) was unambiguous: **stop fragmenting,
absorb everything into one structural plan, ship as v3.10.0**. Issues #4 and #6
are critical regressions that justify the scope expansion. The deliberate
narrowing of v1 of 00103 was right at that point in time (3 FATAL reviews); now
the structural work is the next slot and the upgrade-flow issues belong with
it because they touch the same files (`venv_resolver.sh`, `upgrade_version.sh`,
`_resolve-venv.sh`, `paths.py`, `write-venv-metadata`).

## Scope

This plan delivers, in order:

1. **Production bug hotfixes** — issues #4, #6, #3 (small, low-risk,
   commit-first to de-risk the rest of the plan).
2. **Canonical resolver library** at `scripts/lib/resolve_venv.sh`.
3. **Five-site collapse to shims** — `_resolve-venv.sh`, `venv-include.bash`,
   `scripts/install/venv_resolver.sh`, `init.sh::_resolve_python_cmd`,
   `scripts/install/venv.sh:venv_lock_hash_matches`.
4. **Upgrade-flow resilience** — issues #1, #2, #5.
5. **Static-check QA gate** `scripts/qa/check_canonical_callers.sh` wired into
   `run_all.sh`.
6. **Multi-host NFS hostname-dimension fail-fast** (R22 from 00103 review #3).
7. **`requires-python` cross-check** on probed bootstrap interpreters (R23).
8. **`set -euo pipefail` exit-vs-return contract** (F17).
9. **Release v3.10.0** via `/release minor`.

## Goals

1. Daemon-cli.sh and health-check.sh work correctly out of the box after a
   fresh install of the released version. **No manual metadata fix required.**
2. Major-version upgrades (e.g. v2.26 → v3.10) work via the skill `upgrade.sh`
   without any of the failure modes documented in the 2026-05-01 field report.
3. Five resolver sites collapse to 3–8-line shims sourcing one canonical
   library; one source of truth for venv resolution.
4. Static check enforces the canonical pattern as the 11th `run_all.sh` gate.
5. Hot-path latency budget for `init.sh::_resolve_python_cmd`: \<5ms median per
   hook fire post-consolidation.
6. All Plan 00103 acceptance tests still pass post-consolidation (no regression
   of the v3.9.1 fixes).
7. The skill `upgrade.sh` fetches the latest version of itself (and the
   delegated upgrade chain) from GitHub before doing destructive work, mirroring
   how `install.sh` already works.
8. v3.10.0 ships via `/release minor` with all 15 release-pipeline gates green.

## Non-Goals

- Idle-window daemon death (field report items #4 and #5 from 00103's
  2026-04-30 report; pre-existing v3.8.2 issue, separate plan).
- Compact-event correlation.
- Hot-path optimisation beyond the 5ms latency budget (further improvements
  belong in a follow-up).
- Anything in Plan 00101 (recap-stoppage / silent-stop) — separate plan, has
  its own active investigation.

## Context & Background

### Field reports

- **Plan 00103** field report (2026-04-30): `paths.py:22 import tomllib` at
  module top crashed under `python3 → 3.9`. Five resolver sites silently fell
  back to retired legacy path. **Shipped in v3.9.1.**

- **This plan's** field report (2026-05-01):
  `context/2026-05-01-field-report-upgrade-issues.md`. Six additional issues
  encountered during an actual v2.26.0 → v3.9.1 upgrade in a Podman overlay-fs
  container. Notable verbatim user observation:

  > "the skill scripts should fetch the LATEST versions from upstream GitHub
  > before orchestrating the upgrade, rather than running whatever version
  > was deployed at install time."

### Prior reviews

The original v1 of Plan 00103 attempted to bundle the patch with the
structural refactor and received three consecutive FATAL Opus reviews:

- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-1-opus.md`
- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-2-opus-dry.md`
- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-3-opus.md`

Findings inherited by this plan (re-verify against live tree before any
code, do not trust prior enumerations verbatim):

- **F12** (verified live 2026-05-01): `resolve_existing_venv_python` has
  **9 distinct caller files**, **10 call sites** (`detect_location.sh` calls
  it twice — once for `PROJECT_ROOT`, once for `HOOKS_DAEMON_DIR`):

  01. `scripts/upgrade_version.sh:86`
  02. `scripts/debug_hooks.sh:22`
  03. `scripts/validate_worktrees.sh:63`
  04. `scripts/detect_location.sh:139` (PROJECT_ROOT)
  05. `scripts/detect_location.sh:146` (HOOKS_DAEMON_DIR)
  06. `scripts/install/venv_resolver.sh:95` (`resolve_venv_dir` wrapper —
      internal self-call)
  07. `scripts/install/project_detection.sh:263`
  08. `scripts/install/rollback.sh:113`
  09. `scripts/qa/run_all.sh:22`
  10. `scripts/qa/run_strategy_pattern_check.sh:36`

  Hostile review C-5 claimed 11; verification gives 9 files / 10 sites
  (the discrepancy is a counting convention — the review may have counted
  files-that-source-`venv_resolver.sh` rather than files-that-call the
  function). Convert to re-export shim, do NOT delete. **Closes hostile
  review C-5 with verified data.**

- **F13**: `init.sh` lives at `/workspace/init.sh` (repo root). Three deploy
  locations exist: skill bundle, self-install repo, downstream clone.
  Source-path resolution must work in all three.

- **F14**: Probe-list `python3` and parameter-expansion `${VAR:-python3}` are
  different syntactic categories — static check covers both.

- **F15**: Explicit per-commit verification gates, not coupled batches.

- **F16**: Acceptance fixture must reproduce multi-Python field-bug topology.

- **F17**: `set -euo pipefail` cascade — canonical library distinguishes
  sourced-as-function (`return`) vs invoked-as-script (`exit`).

- **F18**: Static check uses positive-include allowlist + inline marker
  comments, not line-anchor allowlist.

- **R17**: Hot-path latency benchmark before/after.

- **R18**: Fingerprint cache chicken-and-egg — fingerprint requires Python
  invocation but cache is keyed on fingerprint.

- **R19**: `HOOKS_DAEMON_PYTHON` override hard-precedence semantics.

- **R21**: Pre-v3.7.0 install upgrade-path circular dependency.

- **R22**: Multi-host NFS no-`HOSTNAME` fail-fast.

- **R23**: Bootstrap `requires-python` cross-check.

- **R24**: `check_canonical_callers.sh` actionable error output.

- **R25**: `upgrade.sh` preflight test sequencing.

## Design Decisions

### Decision 1: Bug fixes ship FIRST as small commits, before any structural work

**Context**: Issues #4 and #6 are active production bugs breaking
`daemon-cli.sh` for v3.9.1 fresh installs. Issue #3 is a small upgrade-path
glitch. None of the three depend on the canonical-library work. Shipping them
first means even if the structural phases hit a wall, the production bugs are
already gone.

**Decision**: Phase 2 (Production bug fixes) lands before Phase 3 (Canonical
library). Each fix is a separate commit with its own daemon-restart
verification.

**Date**: 2026-05-01

### Decision 2 (REVISED 2026-05-01 after hostile review F-1): drop `.resolve()` at `cli.py:1415`

**Earlier (incorrect) diagnosis** — left here for the audit trail: I claimed
`write-venv-metadata` recorded the calling Python's `argv[0]` and proposed
switching to `sys.executable`. The hostile review proved this wrong by reading
the live code:

```python
# src/claude_code_hooks_daemon/daemon/cli.py:1394-1416
def cmd_write_venv_metadata(args: argparse.Namespace) -> int:
    venv_path = Path(args.venv_path)
    ...
    python_binary = venv_path / "bin" / "python"
    ...
    meta = DaemonVenvMetadata(
        python_path=str(python_binary.resolve()),   # ← line 1415 — THE BUG
        ...
    )
```

The function already constructs `python_binary` from `--venv-path`. The bug is
the `.resolve()` call: on a fresh venv, `bin/python` is a 3-link chain
`bin/python → bin/python3 → /usr/bin/python3`, so `Path.resolve()` returns
the base interpreter. `Path.absolute()` (or no normalisation) returns the
venv path correctly. **Verified live** on this machine:

```
bin/python      -> python3
bin/python3     -> /usr/bin/python3
bin/python3.11  -> python3
Path('.../bin/python').resolve()  → /usr/bin/python3.11   (broken)
Path('.../bin/python').absolute() → /workspace/untracked/venv-py311-66bbc57c/bin/python
```

**Decision**: Replace `str(python_binary.resolve())` with
`str(python_binary)` (already absolute because `args.venv_path` is absolute;
no normalisation needed and none correct). Add a regression test that
constructs a fixture venv with the symlink chain and asserts the recorded
`python_path` is the venv path, not the base interpreter.

**No changes to `paths.py resolve-venv`.** The hostile review's F-2 finding
is upheld: Decision 2.B (formerly proposed disk-construction over the
metadata field) is **DELETED**. It would invert Plan 00100's
metadata-authoritative SSOT contract and create a regression where, with two
fingerprint-keyed venvs sharing one daemon dir, the disk-constructed path
picks the wrong one. Metadata stays authoritative. The fix is in
`write-venv-metadata`, not the resolver.

**Date**: 2026-05-01 (revised after Opus hostile review F-1, F-2)

### Decision 3 (REVISED 2026-05-01 after hostile review C-3): skill scripts self-bootstrap from a pinned release tag, not `main`

**Context** (issue #1, hostile review C-3): The skill scripts deployed at
v2.26.0 hardcoded the legacy venv path. They must fetch a fresh copy before
doing destructive work. The earlier draft of Decision 3 said "download from
`main`" — the hostile review correctly flagged this as irreproducible
(no version pin), MITM-able (size check is theatre), and missing a recursion
guard.

**Decision**:

1. **Pin to release tag, not `main`.** Skill `upgrade.sh` resolves the *target*
   release tag (the one being upgraded *to* — either the latest GitHub release
   or an explicit `--version` argument) and downloads the script set from
   that tag's release artifact, not from a moving branch.
2. **Checksum, not size.** The release pipeline (Step 14 in `RELEASING.md`)
   gains a step that publishes a `bootstrap-checksums.txt` artifact alongside
   the GitHub release, listing sha256 sums for `upgrade.sh`, `daemon-cli.sh`,
   `health-check.sh`, `init-handlers.sh`. The skill `upgrade.sh` downloads
   the checksum file, verifies the GitHub-attestation signature on the
   release tag, then verifies each downloaded script against the listed
   sha256.
3. **Recursion guard.** The freshly-downloaded `upgrade.sh` is invoked with
   `--already-bootstrapped` so it skips the self-bootstrap path. Without
   the flag the freshly-downloaded copy would attempt its own self-bootstrap
   and we'd loop. The flag is also accepted by `daemon-cli.sh`, `health-check.sh`,
   `init-handlers.sh`.
4. **Network failure fallback** is explicit: if the tag-pinned download
   fails (offline, GitHub down), abort with a directive and a documented
   manual-bootstrap path. **No silent fallback to local stale copy** — that
   re-creates the original bug.

**Closes hostile review C-3, H-2.**

**Date**: 2026-05-01 (revised after Opus hostile review C-3)

### Decision 3.B: ALL initially-deployed skill scripts self-bootstrap, not just `upgrade.sh`

**Context** (hostile review H-2): Issue #1's fix as originally scoped only
covered `upgrade.sh`. But `daemon-cli.sh`, `health-check.sh`, and
`init-handlers.sh` are also shipped at install time and remain stale until
a successful upgrade redeploys them. A v3.10.0 user whose `daemon-cli.sh`
was deployed at v2.26.0 still hits the legacy-path bug even after fix #4
ships, because *their* `daemon-cli.sh` doesn't know about the new metadata
contract.

**Decision**: All four skill scripts (`upgrade.sh`, `daemon-cli.sh`,
`health-check.sh`, `init-handlers.sh`) gain a self-bootstrap stanza using
the same Decision 3 mechanism (pinned tag, checksum, recursion guard).
Bootstrap is always on for `upgrade.sh`; for the other three it is gated
by a configurable cache (e.g. once per 24h or once per session) so they
don't hit GitHub every hook fire.

**Date**: 2026-05-01

### Decision 3.C: which `upgrade.sh`?

**Context** (hostile review M-1): two `upgrade.sh` files exist:
`scripts/upgrade.sh` and
`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh`.

**Decision**: Decisions 3 and 3.B target the **skill** `upgrade.sh` —
`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh` (the
one shipped to user projects via the `hooks-daemon` skill bundle). The
repo-internal `scripts/upgrade.sh` is developer tooling and unaffected.

**Date**: 2026-05-01

### Decision 4 (REVISED 2026-05-01 after hostile review C-4): `upgrade_version.sh` is the ONLY caller that gets the bootstrap fallback

**Context** (issue #2, hostile review C-4): Calling `resolve_existing_venv_python`
first means a fresh major-version upgrade aborts before it has a chance to
create the new fingerprint-keyed venv. The earlier draft proposed widening
the function's contract; the hostile review correctly noted that
`resolve_existing_venv_python` has many callers, some of which legitimately
want hard-fail-on-missing-venv (diagnostics, health-check, validate-worktrees),
not auto-bootstrap.

**Caller enumeration (verified live 2026-05-01)** — see F12 above for the
authoritative list. Per-caller intent:

- **AUTO-BOOTSTRAP** (fall back to `ensure_venv`):
  `scripts/upgrade_version.sh:86` — and only this one. It is the unique
  caller that knows the user just asked to upgrade and that creating a
  venv is the appropriate next step.
- **HARD-FAIL** (no fallback, error if no venv) — all other 9 call sites:
  `debug_hooks.sh`, `validate_worktrees.sh`, `detect_location.sh` (×2),
  `venv_resolver.sh:resolve_venv_dir` (internal), `project_detection.sh`,
  `rollback.sh`, `qa/run_all.sh`, `qa/run_strategy_pattern_check.sh`.

Note: the skill-side scripts (`daemon-cli.sh`, `health-check.sh`,
`init-handlers.sh`) source `_resolve-venv.sh` (a separate parallel
implementation), not `venv_resolver.sh` — that parallel implementation
is exactly what Phase 5 collapses into the canonical library.

**Decision**: Do NOT widen `resolve_existing_venv_python`. Instead,
`upgrade_version.sh` calls `resolve_existing_venv_python` and on failure
explicitly invokes `ensure_venv "$DAEMON_DIR" "$INSTALLED_VERSION" "$BOOTSTRAP_PYTHON"`
with the bootstrap Python (resolved via the explicit-versioned probe used by
`install.sh`). The bootstrap Python drives `uv sync`; once the new venv
exists, the rest of the upgrade runs through it.

All other callers retain their existing fail-fast behaviour. **Closes
hostile review C-4, C-5.**

**Date**: 2026-05-01 (revised after Opus hostile review C-4, C-5)

### Decision 5: Daemon installer adds `uv.lock` to `.gitignore` for the daemon directory

**Context** (issue #3): Untracked `uv.lock` was present in the user's
`.claude/hooks-daemon/`, blocking `git checkout` during version switching.
The file is generated by `uv sync`; it should not be tracked in the daemon's
own git tree, and any stray copy in the user's checkout should be cleaned
or ignored before checkout.

**Decision**:

1. The daemon's own `.gitignore` (in the daemon repo) lists `uv.lock` so it
   is never tracked.
2. Skill `upgrade.sh` (after self-bootstrap, before `git fetch + checkout`)
   removes any `uv.lock` it finds in the daemon directory. This is safe
   because `uv sync` regenerates it during venv setup.

**Date**: 2026-05-01

### Decision 6 — 8: Inherited from prior 00104 design

**6. Canonical bash library** at `scripts/lib/resolve_venv.sh` with public API
(`resolve_venv_python`, `resolve_venv_dir`). Sourced-as-function uses `return`;
invoked-as-script uses `exit`.

**7. Static check `check_canonical_callers.sh`** added as 11th `run_all.sh`
gate. Positive-include allowlist; inline `# canonical-resolver-exempt:` marker
comments for legitimate exceptions.

**8. Multi-host NFS hostname fail-fast**: when `HOSTNAME` is unset AND multiple
hostname-suffixed venvs exist, fail fast with a clear directive listing the
discovered hostnames so the operator can pick one explicitly.

## Tasks

### Phase 1: Design refresh + Opus hostile review gate

- [x] ✅ **Task 1.1** (DONE 2026-05-01): Re-grep the live tree.
  - `resolve_existing_venv_python` caller list verified — see F12 above
    (9 files, 10 call sites). Hostile review C-5's 11-figure was a
    different counting convention.
  - Issue #4 root cause verified live: `cli.py:1415` `.resolve()` follows
    `bin/python → bin/python3 → /usr/bin/python3` symlink chain. Fix is
    one line. (See Decision 2 revision.)
- [x] ✅ **Task 1.2** (DONE 2026-05-01): Opus 4.6 hostile review captured at
  `context/2026-05-01-review-1-opus-hostile.md`. Verdict was REJECT with
  2 FATAL, 6 CRITICAL, 3 HIGH, 3 MEDIUM, 1 NIT. **All FATAL and CRITICAL
  findings are addressed in the revisions to Decisions 2, 3, 3.B, 3.C, 4
  and the F12 verification above.** HIGH findings H-1, H-2, H-3 are
  addressed by Tasks 9.6, Decision 3.B, Phase 5 per-commit gates
  (respectively). C-6 is addressed by Task 5.3.
- [ ] ⬜ **Task 1.3**: Final plan-amendment commit. After this commit
  lands, the plan is locked: any further design change requires a
  fresh hostile review pass.

### Phase 2: Production bug hotfixes (low-risk, ship FIRST)

These three fixes are independent of the structural work and ship as separate
commits at the start of the plan. They de-risk the rest by narrowing the diff
that gets blamed if anything breaks during structural phases.

- [ ] ⬜ **Task 2.1 — Issue #4 fix (one-line, post-review-revised)**:
  - [ ] ⬜ Failing test: `tests/unit/daemon/test_cli_write_venv_metadata.py::test_python_path_records_venv_path_not_resolved_base`
    — fixture creates a temp venv with the `bin/python → bin/python3 → /usr/bin/python3` symlink chain; invokes `cmd_write_venv_metadata`;
    asserts the JSON `python_path` equals the venv's `bin/python` path
    (NOT the system Python the symlinks resolve to).
  - [ ] ⬜ Implement: `src/claude_code_hooks_daemon/daemon/cli.py:1415` —
    change `str(python_binary.resolve())` to `str(python_binary)`. The
    path is already absolute (constructed from `args.venv_path` which is
    an absolute Path); no normalisation is needed and `.resolve()`
    follows symlinks which is exactly the bug.
  - [ ] ⬜ NO changes to `paths.py resolve-venv`. Hostile review F-2
    upheld: metadata is authoritative per Plan 00100; the disk-construction
    "fallback" originally proposed in Decision 2.B is DELETED.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 2.2 — Issue #6 (DOWNSTREAM PHANTOM of Issue #4 — verified
  2026-05-01 against `src/.../skills/.../scripts/health-check.sh`)**:
  - The field-report described "the script body invokes the daemon CLI via a
    separate hardcoded path rather than `$PYTHON`". Live grep of v3.9.1
    `health-check.sh` (`grep -nE 'python|claude_code_hooks_daemon'`) shows
    every daemon-CLI invocation uses `"$PYTHON"`: lines 45, 64, 82, 92. There
    is no separate hardcoded path. What the field-report user observed was
    `$PYTHON` resolving to `/usr/bin/python3.11` because the metadata file
    stored the wrong `python_path` (Issue #4). Fixing Task 2.1 fixes this.
  - [ ] ⬜ Add static-source regression test
    `tests/integration/test_health_check_script_uses_resolved_python.py` that
    parses `health-check.sh` and asserts every `claude_code_hooks_daemon.daemon.cli`
    invocation is preceded by `"$PYTHON"`. Catches any future regression that
    re-introduces a hardcoded interpreter path.
  - No implementation change needed — Task 2.1 closes the underlying defect.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 2.3 — Issue #3 fix**:
  - [ ] ⬜ Add `uv.lock` to the daemon repo's `.gitignore` if not already
    present.
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_handles_stale_uv_lock.py`
    — fixture daemon dir with stray `uv.lock`; asserts skill `upgrade.sh`
    cleans it before `git checkout` (test will land green after Task 5.1
    implements the cleanup; for now mark xfail with reason).
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

### Phase 3: TDD failing tests for structural work

- [ ] ⬜ **Task 3.1**: Parity matrix test — every site returns the same Python
  for the same daemon-dir input.
- [ ] ⬜ **Task 3.2**: `set -euo pipefail` cascade test —
  `test_resolver_when_sourced_under_pipefail_does_not_kill_caller_shell`.
- [ ] ⬜ **Task 3.3**: Hot-path latency benchmark — measure
  `init.sh::_resolve_python_cmd` median time over N hook fires; assert \<5ms
  post-consolidation.
- [ ] ⬜ **Task 3.4**: Multi-host NFS fail-fast test — fixture with two
  hostname-suffixed venvs, `HOSTNAME` unset, asserts fail-fast with a directive
  listing the hostnames.
- [ ] ⬜ **Task 3.5**: Static-check tests — positive-include allowlist
  passes the canonical library, inline marker comments pass tagged exceptions,
  legitimate violations are flagged.
- [ ] ⬜ **Task 3.6**: `requires-python` cross-check test — bootstrap rejects
  an interpreter outside `pyproject.toml`'s `requires-python` even when
  `>= 3.11`.

### Phase 4: Canonical library — `scripts/lib/resolve_venv.sh`

- [ ] ⬜ **Task 4.1**: Write `scripts/lib/resolve_venv.sh` with public API:
  - `resolve_venv_python <daemon_dir>` → echo path or fail.
  - `resolve_venv_dir <daemon_dir>` → echo dir or fail.
  - Sourced-as-function: `return` non-zero. Invoked-as-script: `exit`
    non-zero. Detection via `${BASH_SOURCE[0]}` vs `$0`.
- [ ] ⬜ **Task 4.2**: Source-path resolution robust across the 3 deploy
  locations (skill bundle, self-install repo, downstream clone).
- [ ] ⬜ **Task 4.3**: Phase 3 Tasks 3.1, 3.2 turn green.
- [ ] ⬜ **Task 4.4**: Daemon restart RUNNING; QA green; commit.

### Phase 5: Five-site shim collapse + upgrade-flow resilience

Each site becomes a 3–8-line shim sourcing the canonical library. `venv_resolver.sh`
collapses to a re-export shim (NOT deletion — F12). One commit per site.

**Per-micro-commit verification gate (H-3, post-review)**: Phase 5 dogfoods
itself — every commit lands on a developer's own daemon. Between consecutive
sub-tasks (5.1 → 5.1.B → 5.2 → ...) the developer MUST run, in this order:

1. `./scripts/qa/run_all.sh` — all 11 checks green.
2. `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
3. `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` — RUNNING.
4. `bash src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/daemon-cli.sh status` — clean.

If any step fails, `git revert` the last commit BEFORE proceeding. This
prevents the failure mode where commits 5.6 and 5.7 each look fine in
isolation but together leave the developer's own daemon broken with no
recovery path.

- [ ] ⬜ **Task 5.1 — Issue #1 fix (skill upgrade self-bootstrap, post-review-revised per Decision 3 + 3.B + 3.C)**:

  - [ ] ⬜ Add release-pipeline step: publish `bootstrap-checksums.txt`
    (sha256 of skill scripts) as a GitHub release artifact. Update
    `CLAUDE/development/RELEASING.md` Step 14 with the new artifact.
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_self_bootstraps.py`
    — fixture skill `upgrade.sh` is intentionally stale (echoes "OLD"); a
    network-mocked release tag exposes a fresh upgrade.sh that echoes "NEW";
    asserts actual run echoes "NEW".
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_recursion_guard.py`
    — fixture freshly-downloaded `upgrade.sh` is invoked with
    `--already-bootstrapped`; asserts the self-bootstrap stanza is skipped
    (no second download).
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_aborts_on_network_failure.py`
    — fixture mocks GitHub unreachable; asserts the script aborts with a
    directive (does NOT silently fall back to local stale copy).
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_checksum_mismatch.py`
    — fixture mocks tampered download; asserts abort with "checksum
    mismatch" directive.
  - [ ] ⬜ Implement Decision 3 in skill `upgrade.sh` only (Decision 3.C —
    `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh`):
    pinned-tag download, sha256 verification against
    `bootstrap-checksums.txt`, `--already-bootstrapped` recursion guard,
    explicit abort on network/checksum failure.
  - [ ] ⬜ Implement post-bootstrap stage: clean any stray `uv.lock` in
    daemon dir before `git checkout`. (Closes Task 2.3 xfail.)
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

- [ ] ⬜ **Task 5.1.B — Decision 3.B fix (daemon-cli.sh / health-check.sh / init-handlers.sh self-bootstrap)**:

  - [ ] ⬜ Failing test:
    `tests/integration/test_diagnostic_scripts_self_bootstrap.py` — fixture
    stale `daemon-cli.sh`; asserts it self-bootstraps from pinned release tag
    on first invocation per session, caches the bootstrap result, does NOT
    re-download on subsequent same-session invocations.
  - [ ] ⬜ Implement: shared `_self_bootstrap.sh` library sourced by all
    four skill scripts; cache marker at
    `$DAEMON_DIR/untracked/.bootstrap-cache.{sha,timestamp}`.
  - [ ] ⬜ Implement: `daemon-cli.sh`, `health-check.sh`,
    `init-handlers.sh` source the bootstrap library and respect the
    `--already-bootstrapped` flag.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

- [ ] ⬜ **Task 5.2 — Issue #2 fix (upgrade_version.sh bootstrap fallback)**:

  - [ ] ⬜ Failing test: `tests/integration/test_upgrade_version_bootstraps_when_no_venv.py`
    — fixture daemon dir with only legacy v2.x stamp (no `.daemon-metadata.json`,
    no fingerprint venv); asserts upgrade succeeds by creating the new venv.
  - [ ] ⬜ Implement: `upgrade_version.sh` falls back to `ensure_venv` with
    bootstrap-resolved Python when `resolve_existing_venv_python` fails.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

- [ ] ⬜ **Task 5.3 — Issue #5 fix (verify_venv overlay-fs race) + C-6 silent-fallback removal**:

  - [ ] ⬜ Reproduce locally on overlay-fs (this repo runs in a Podman
    container so reproduction is in-tree).
  - [ ] ⬜ Failing test: `tests/integration/test_verify_venv_after_uv_link_copy.py`
    — fixture forces `UV_LINK_MODE=copy`, asserts `verify_venv` succeeds
    after the sync without needing manual retry.
  - [ ] ⬜ Failing test:
    `tests/integration/test_venv_sh_sync_failure_is_visible.py` —
    `scripts/install/venv.sh:465` currently does
    `sync -f "$venv_path" 2>/dev/null || sync` which hides real failures
    (project memory: `feedback_silent_fallback_antipattern.md`). Asserts
    that when `sync -f` fails for a non-overlay-fs reason, the failure
    surfaces (stderr captured/logged, not silenced). Closes hostile
    review C-6.
  - [ ] ⬜ Implement: `verify_venv` retries on transient
    `ModuleNotFoundError` / missing-binary errors with a small bounded sleep
    loop (e.g. 5 attempts × 200ms) when `UV_LINK_MODE=copy` was used. Flag
    that this is a workaround for overlay-fs visibility, not the canonical
    expected path.
  - [ ] ⬜ Implement: remove `2>/dev/null` from `venv.sh:465`. If
    `sync -f` fails for the documented overlay-fs reason, the retry loop
    above absorbs it. For any other failure mode the stderr now reaches
    the user. (See feedback memory `silent fallback hides regressions`.)
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

- [x] ✅ **Task 5.4**: `_resolve-venv.sh` collapses to canonical shim. (2026-05-01, commit 2fc0e30)

- [x] ✅ **Task 5.5**: `venv-include.bash` collapses to canonical shim. (2026-05-01)

- [x] ✅ **Task 5.6**: `venv_resolver.sh` collapses to re-export shim
  preserving all 9 caller signatures. (2026-05-01)

- [x] ✅ **Task 5.7**: `init.sh::_resolve_python_cmd` collapses; preserves
  fingerprint cache write. (2026-05-01 — done-by-Phase-4 commit 50224d6.
  init.sh:263-282 is already a 20-line shim sourcing
  `${HOOKS_DAEMON_ROOT_DIR}/scripts/lib/resolve_venv.sh` and delegating to
  `resolve_venv_python`. The bespoke fingerprint/scan ladder was removed in
  Phase 4. No fingerprint cache write exists today — Phase 8 Task 8.1 adds
  `untracked/.python-cmd-cache` on top of the canonical library. The shim
  preserves the surface needed for that future write: `_resolve_python_cmd`
  remains the single hot-path entry, and the canonical library is the only
  layer that needs cache logic added. Verified by parity matrix tests

  - pipefail cascade tests + hot-path latency harness smoke.)

- [x] ✅ **Task 5.8**: `venv.sh:venv_lock_hash_matches` collapses. (2026-05-01
  — added public helper `resolve_venv_python_in_venv <venv_path>` to the
  canonical library and rewired `venv_lock_hash_matches` to source the lib
  and delegate. The bare `bin/python`-only assumption is gone — the
  canonical helper falls through to `bin/python3` when only that exists,
  matching paths.py `_pick_interpreter`. In-place fallback retained for
  the chicken-and-egg case where venv.sh is sourced before the lib is on
  disk: bin/python preferred, bin/python3 fallback, hard-fail otherwise.
  Verified: 24/24 targeted (parity matrix + pipefail cascade + install
  resolver + ensure_venv + paths check-venv-fresh), 11/11 QA, daemon
  RUNNING.)

### Phase 6: Static-check QA gate

- [ ] ⬜ **Task 6.1**: Author `scripts/qa/check_canonical_callers.sh` per
  Decision 7. Positive-include allowlist; inline `# canonical-resolver-exempt:`
  marker support; actionable error output (R24).
- [ ] ⬜ **Task 6.2**: Wire into `run_all.sh` as the 11th check.
- [ ] ⬜ **Task 6.3**: Phase 3 Task 3.5 turns green; full QA passes (11/11).
- [ ] ⬜ **Task 6.4**: Daemon restart RUNNING; commit.

### Phase 7: Multi-host NFS + `requires-python` cross-check

- [ ] ⬜ **Task 7.1**: Multi-host fail-fast logic in canonical library; Phase 3
  Task 3.4 turns green.
- [ ] ⬜ **Task 7.2**: `requires-python` cross-check in bootstrap probe; Phase
  3 Task 3.6 turns green.
- [ ] ⬜ **Task 7.3**: Daemon restart RUNNING; QA green; commit.

### Phase 8: Hot-path latency verification

- [ ] ⬜ **Task 8.1**: Run Phase 3 Task 3.3 benchmark against the consolidated
  code. If median exceeds 5ms, optimise `source` cost in `init.sh`
  (e.g. cache the canonical library's resolved output via the existing
  `untracked/.python-cmd-cache` mechanism). Document optimisation in plan.
- [ ] ⬜ **Task 8.2**: Daemon restart RUNNING; commit.

### Phase 9: Verification + acceptance

- [ ] ⬜ **Task 9.1**: Re-run all Plan 00103 acceptance tests
  (`tests/acceptance/test_v391_field_regression.py`) — must still pass.
- [ ] ⬜ **Task 9.2**: New acceptance test mirroring the 2026-05-01 field
  report scenario:
  - Container fixture with overlay-fs (or filesystem mock).
  - Skill `upgrade.sh` from a stale-pinned starting point.
  - Stray `uv.lock`.
  - Asserts the upgrade succeeds end-to-end with the new code.
- [ ] ⬜ **Task 9.3**: Final full `./scripts/qa/run_all.sh` — all 11 checks
  pass.
- [ ] ⬜ **Task 9.4**: Daemon restart RUNNING.
- [ ] ⬜ **Task 9.5**: Live diagnostic test from project root: `health-check.sh`,
  `daemon-cli.sh status`, `init-handlers.sh` — all clean. **Confirms issues #4
  and #6 are gone in the integrated build.**
- [ ] ⬜ **Task 9.6 — Concrete H-1 acceptance gate (post-review)**:
  - [ ] ⬜ Author `tests/acceptance/test_diagnostic_scripts.py` with
    deterministic test cases:
    1. Fresh-install metadata is correct: a fixture project that just ran
       `install.sh` has `.daemon-metadata.json:python_path` pointing at the
       venv's `bin/python`, NOT `/usr/bin/python3.11`.
    2. `daemon-cli.sh status` from a fresh install runs without
       `ModuleNotFoundError`.
    3. `health-check.sh` from a fresh install runs without
       `ModuleNotFoundError`.
    4. Skill `upgrade.sh` self-bootstrap produces the latest version (mock
       release tag).
    5. Skill `upgrade.sh` aborts on network failure with directive (no
       silent fallback).
    6. Stale `daemon-cli.sh` self-bootstraps on first invocation per
       session (Decision 3.B).
  - [ ] ⬜ Wire into release pipeline Step 12 (Acceptance Testing Gate)
    explicitly so v3.10.0 cannot ship without these passing. Update
    `CLAUDE/development/RELEASING.md` Step 12 with the test reference.
  - [ ] ⬜ Run the suite locally; all green; commit.

### Phase 10: Release v3.10.0

- [ ] ⬜ **Task 10.1**: Run `/release minor` skill end-to-end. All 15 release
  pipeline gates must pass.
- [ ] ⬜ **Task 10.2**: Release notes: explicit transparency about every
  shipped fix (issues #1–#6 plus the structural consolidation). Reference the
  field report from 2026-05-01 verbatim.
- [ ] ⬜ **Task 10.3**: Acceptance gate covers diagnostic-script invocation
  paths (the v3.9.0 regression escaped because acceptance focused on hook
  dispatch).
- [ ] ⬜ **Task 10.4**: Verify release published, tag pushed, GitHub release
  marked latest.
- [ ] ⬜ **Task 10.5**: Plan completion checklist (move folder to
  `Completed/`, update `README.md`, etc.).

## Dependencies

- **Depends on**: Plan 00103 complete (v3.9.1 released — yes, complete).
- **Blocks**: Future hot-path optimisation work, multi-host deployment work.
- **Related**: Plan 00100 (venv SSOT — this plan refines its shell-wrapper
  layer with the DRY library).

## Success Criteria

- [ ] On a fresh install of v3.10.0: `daemon-cli.sh status` works without any
  manual `.daemon-metadata.json` patching. **Issue #4 closed.**
- [ ] On a fresh install of v3.10.0: `health-check.sh` reports daemon health
  without `ModuleNotFoundError`. **Issue #6 closed.**
- [ ] Major-version upgrade (v2.26 → v3.10) via the skill `/hooks-daemon upgrade` succeeds without manual intervention; no stale-skill-script
  failure, no `uv.lock` checkout abort, no bootstrap paradox.
  **Issues #1, #2, #3, #5 closed.**
- [ ] `scripts/lib/resolve_venv.sh` exists with documented public API.
- [ ] All five resolver sites are 3–8-line shims sourcing the canonical.
- [ ] `venv_resolver.sh` retained as re-export shim (9 caller files / 10
  call sites preserved per F12).
- [ ] `scripts/qa/check_canonical_callers.sh` wired into `run_all.sh` and
  passes (11/11).
- [ ] Hot-path latency: `init.sh::_resolve_python_cmd` median resolve \<5ms
  verified by benchmark.
- [ ] Multi-host NFS without `HOSTNAME` set fails fast with clear directive
  when multiple hostname-suffixed venvs exist.
- [ ] Bootstrap rejects interpreter outside `requires-python` even when
  `>= 3.11`.
- [ ] Sourced-as-function paths use `return`; invoked-as-script paths use
  `exit`. Test verifies `venv-include.bash` does not kill caller shell on
  `set -euo pipefail`.
- [ ] All Plan 00103 acceptance tests still pass after consolidation.
- [ ] Each commit in Phase 5 leaves daemon RUNNING and QA green.
- [ ] v3.10.0 released via `/release minor` with all 15 gates green.

## Risks & Mitigations

| Risk                                                                                      | Impact | Probability   | Mitigation                                                                                                                                                                            |
| ----------------------------------------------------------------------------------------- | ------ | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| This plan re-creates the v1 ambitious-bundle anti-pattern that earned three FATAL reviews | High   | Medium        | Phase 1 hostile review gate before any code. Phase 2 ships bug fixes as standalone commits so they survive even if structural phases stall. Per-commit verification gates throughout. |
| Skill `upgrade.sh` self-bootstrap introduces network failure modes                        | High   | Medium        | Self-bootstrap is best-effort with explicit timeout; falls back to running the locally-deployed version with a warning. Test `test_skill_upgrade_falls_back_when_github_unreachable`. |
| `write-venv-metadata` change breaks downstream consumers reading `python_path` field      | Medium | Low           | The field semantics tighten (now correctly records calling Python); resolver no longer trusts it as source of truth. Audit for external consumers in Phase 1.                         |
| `verify_venv` retry loop masks a real bug elsewhere                                       | Medium | Medium        | Retry is bounded (5 × 200ms = 1s max). Logs warn when retry was needed. Phase 9 acceptance test confirms first-attempt success in normal conditions.                                  |
| Source-path resolution fragility across 3 deploy locations                                | High   | Medium        | Explicit deploy-location enumeration in Phase 4. Test fixture per location.                                                                                                           |
| Hot-path latency regression after consolidation                                           | Medium | Medium        | Phase 8 benchmark gate. Roll back consolidation if latency exceeds budget.                                                                                                            |
| Static check false positives on documentation/release notes                               | Medium | High          | Phase 6 positive-include allowlist; inline marker comments per F18.                                                                                                                   |
| Incomplete `venv_resolver.sh` caller enumeration (F12 root cause)                         | High   | Low           | Phase 1 design refresh re-greps the live tree.                                                                                                                                        |
| `set -euo pipefail` cascade kills caller shell (F17)                                      | High   | High if naive | Phase 4 explicit exit-vs-return contract. Phase 3 Task 3.2 covers it.                                                                                                                 |
| Self-install dogfooding: developer's own venv breaks while applying this plan             | High   | Low           | This repo IS a self-install. Each commit's daemon-restart-RUNNING check catches it. Revert plan: `git revert` any commit that breaks `daemon-cli.sh status`.                          |

## Notes & Updates

### 2026-04-30 — Plan stub created (split from v1 ambitious 00103)

- v1 (`PLAN-v1-ambitious-superseded.md` in 00103) attempted to combine the
  patch fix with a DRY consolidation. Three Opus 4.6 hostile reviews returned
  FATAL.
- This plan was originally scoped to DRY consolidation only.

### 2026-05-01 — Plan amended after Opus 4.6 hostile review

- Hostile review at `context/2026-05-01-review-1-opus-hostile.md` returned
  REJECT (2 FATAL, 6 CRITICAL, 3 HIGH, 3 MEDIUM, 1 NIT).
- F-1 verified live: Issue #4 root cause is `cli.py:1415` `.resolve()`
  symlink-following, NOT missing `sys.executable`. Decision 2 rewritten;
  fix is now a one-line change.
- F-2 upheld: Decision 2.B (disk-construction over metadata) DELETED — it
  inverted Plan 00100's metadata-authoritative SSOT contract.
- C-3: Decision 3 rewritten to pin self-bootstrap to release tag (not
  `main`), with sha256 verification and `--already-bootstrapped` recursion
  guard. Network failure aborts explicitly (no silent fallback).
- C-4 / C-5: Caller enumeration verified live — 9 files / 10 call sites
  (not 11 as review claimed; review was right that prior figure of 9 was
  *also* wrong — verification gives the authoritative list).
- C-6: `venv.sh:465` silent `2>/dev/null` removal added to Task 5.3.
- H-1: Concrete `tests/acceptance/test_diagnostic_scripts.py` added as
  Task 9.6, wired into release pipeline Step 12.
- H-2: Decision 3.B added — all four skill scripts self-bootstrap, not
  just `upgrade.sh`. Task 5.1.B drives the implementation.
- H-3: Explicit per-micro-commit verification gate added at start of
  Phase 5 (dogfooding self-recovery).
- M-1: Decision 3.C clarifies which `upgrade.sh` is targeted (skill
  bundle, not `scripts/upgrade.sh`).
- Plan is now ready for implementation. Phase 1 closed (review was the
  Phase 1 deliverable). Phase 2 begins with the one-line `cli.py:1415`
  fix.

### 2026-05-01 — Plan rewritten to absorb 2026-05-01 field report

- 2026-05-01 field report (`context/2026-05-01-field-report-upgrade-issues.md`)
  surfaced 6 production issues from a real v2.26 → v3.9.1 upgrade.
- User direction: "stop beating about the bush ... ONE single plan, all the
  work in there in the correct order. Get it all done, get it through the
  release process and get it released."
- Rewrite folds issues #1–#6 into the structural plan with explicit ordering
  (bug fixes first, structural after, release as v3.10.0).
- Issue #4 alone (broken `python_path` in metadata) justifies the scope
  expansion; it breaks `daemon-cli.sh` for every fresh install of v3.9.1.
- Plan 00105 / 00106 NOT created — single plan absorbs everything.
