# Plan 00395: running daemon detects source changed underneath it

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

A daemon loads its code once and serves it for the life of the process. When a
DIFFERENT session or process on the same filesystem upgrades that installation,
**the running daemon keeps serving what it loaded at startup and never says
so.** Every safety handler in the process is then the old version, and the only
symptom is behaviour that silently does not match what is installed.

The verified gap: `DaemonController._source_fingerprint` is assigned once in
`initialise()` (`controller.py:312`) and thereafter only read
(`controller.py:1120`, the health response). The only automatic caller of the
staleness comparison is `scripts/qa/run_smoke_test.sh` during a full QA sweep.
Nothing re-checks while the daemon is alive.

## CORRECTION — the first revision of this plan was built on ground I never established

**This section stays.** The first revision proposed a per-dispatch ctime sweep
over all 535 `.py` files plus a sha256 fingerprint comparison. That is the wrong
instrument for the reported problem, and the reason is worth recording because
the mistake is repeatable.

The owner reported a **version** being updated underneath a running daemon. The
daemon already records the installed version and already reads it at startup:

```text
.daemon-metadata.json  (inside the venv)
  daemon_version   vX.Y.Z, or vX.Y.Z+<ref>.<sha> for a guarded branch install
  lock_hash        sha256:<64 hex>
  written_at       timestamp
  # docstring: "read by the daemon on every startup"
```

An upgrade writes that file. So "has my version changed underneath me?" is a
re-resolve plus one small JSON read — not a sweep over the whole package.

**How the first revision went wrong**: it began by grepping `src/` for an
adjacent mechanism, found Plan 00371's source fingerprints, and designed around
the first mechanism it met rather than establishing how the daemon is actually
deployed and versioned. It then sampled ONE deployment mode — this
self-install repo, where `.claude/hooks-daemon/` has no `.git` — and generalised
from it, without reading `CLAUDE/LLM-INSTALL.md` or `CLAUDE/SELF_INSTALL.md`,
which own that fact and are listed in `CLAUDE/CLAUDE.md`'s routing table. There
are two modes: a client project holds a gitignored CLONE at
`.claude/hooks-daemon/`; this repo is self-install and the Layer 2 installer
aborts if it detects that mode.

Investment then compounded the error — a cost measurement and a full design were
committed on top of the unestablished foundation before anyone checked it.

## The mechanism, established rather than assumed

Read out of `CLAUDE/SELF_INSTALL.md` ("Venv layout"), `metadata.py` and
`scripts/upgrade.sh`:

- The venv is **fingerprint-keyed**: `untracked/venv-{slug}-py{MM}-{fingerprint}/`,
  composed by `paths.py` (`python_venv_fingerprint()`, `get_daemon_venv_path()`).
- `.daemon-metadata.json` lives INSIDE that venv and is written atomically
  (`.tmp` then `Path.replace()`), so a reader never sees a half-written file.
- `scripts/upgrade.sh` emits metadata at the tail of an upgrade, resolving the
  venv by globbing `untracked/venv-*py3*/bin/python`, first match wins.

**The subtlety that decides the design**: because the venv name embeds a
fingerprint, an upgrade that changes the fingerprint inputs creates a NEW venv
directory rather than rewriting the old one. A check that re-reads the path it
remembered at startup would therefore see an untouched file and report fresh.
The check must **re-resolve** the venv path and compare that too.

## Two tiers, and only one of them is this plan's business

| Tier | Question                                                           | Signal                                                                                    | Status                                                            |
| ---- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1    | Has the installed VERSION changed under me?                        | re-resolve venv + `.daemon-metadata.json` (`daemon_version`, `written_at`, resolved path) | **this plan**                                                     |
| 2    | Has SOURCE changed without a version change (an uncommitted edit)? | the Plan 00371 fingerprint                                                                | already exists as `check-source-fresh`, `daemon_restart_verifier` |

Tier 2 matters mainly when dogfooding this repo, and it is already served. This
plan must not quietly re-solve it.

## The ctime finding — kept, but scoped honestly

Measured, and still true: a `cp -p` over changed content left **mtime AND inode
unchanged** while ctime advanced (`mtime=…874` before and after, `ctime=…874 → …875`). So an mtime- or inode-gated staleness check silently misses an
installer-style redeploy.

**This does not apply to tier 1** — reading a small JSON file needs no gate at
all. It is recorded here because it is a real trap that would bite anyone who
later builds tier 2 as a live check, and because the ccy supervisor's worker
reload already documents the same trap. It is evidence for a future decision,
not a justification for this one.

## The action on detection is ALREADY RULED — do not re-open it

The owner's standing ruling: **advise loudly, name the command; never
auto-restart, never auto-upgrade.** That is what Plans 00386 and 00389 shipped.
This plan decides where the check runs, not what it does when it fires.

## The open question — where the check runs

Much narrower now that the signal is one small file:

1. **On hook dispatch.** A re-resolve plus a small JSON read is cheap enough to
   need no gate. Catches the mid-session case, which is the reported problem.
2. **SessionStart only.** Cheaper still, but a session already in flight never
   re-checks — which is exactly the reported case, so this is insufficient alone.
3. **Writer announces.** `scripts/upgrade.sh` signals any running daemon. Exact
   and nearly free, but only covers changes made through that script.

## Goals

- A running daemon whose installed version changed says so, unasked, while it is
  still running.
- The check survives an upgrade that creates a NEW fingerprint-keyed venv.
- It reuses the existing metadata reader rather than inventing a second one.
- On detection: advise loudly, name the restart command, never self-restart.

## Non-Goals

- Auto-restarting or hot-reloading. Ruled out by the owner's standing position.
- Re-solving tier 2. `check-source-fresh` and `daemon_restart_verifier` own it.
- Config drift. `.daemon-metadata.json` does not track `hooks-daemon.yaml`
  contents; Plan 00389 owns config drift and this plan must not half-cover it.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner picks the placement — option 1, 2, 3, or a
  combination.

### Phase 2: Build, once decided

- [ ] ⬜ **Task 2.1**: A failing test first: a daemon started against one venv,
  then an upgrade that writes a NEW fingerprint-keyed venv, must be reported
  stale. That is the case a remembered-path check passes wrongly, so it is the
  test that must exist before the check is written.
- [ ] ⬜ **Task 2.2**: A second failing test for the in-place case — same venv,
  `.daemon-metadata.json` rewritten with a new `daemon_version`.
- [ ] ⬜ **Task 2.3**: Implement using the existing `read_daemon_metadata` and
  venv resolution. No second metadata reader.
- [ ] ⬜ **Task 2.4**: Pin that the advisory names the restart command and that
  nothing restarts itself.
- [ ] ⬜ **Task 2.5**: Pin the fail-open contract: unreadable, missing or
  malformed metadata must never block a hook. `read_daemon_metadata` already
  collapses those to `None`.

## Success Criteria

- [ ] A running daemon whose installed version changed reports itself stale
  without being asked.
- [ ] It reports stale when the upgrade created a NEW venv, proven by a test
  that fails against a remembered-path-only check.
- [ ] The advisory names the restart command and nothing restarts itself.
- [ ] A missing or malformed metadata file allows the hook through.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Raised by the owner: the daemon detects being out of date, but not being
  updated underneath it by another session on the same filesystem.
- First revision (`a64dca90`, `57d6b435`) designed a package-wide fingerprint
  sweep without establishing the deployment model, and was corrected after the
  owner challenged it. The correction is kept in this document rather than
  quietly rewritten, because the failure mode — design before ground truth, then
  generalise from one sample — is the reusable lesson.
- That failure is itself the subject of a follow-up: can the daemon detect a
  plan written without reading the docs that own its domain?
