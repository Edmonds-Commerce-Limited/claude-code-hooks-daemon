# Plan 00395: running daemon detects source changed underneath it

**Status**: In Progress
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

## SETTLED — this is only relevant to a CLIENT install

Owner ruling, and a constraint neither earlier revision had: **in self-install
mode this check is irrelevant and must be dormant.** In self-install the daemon
runs from `src/` in the repository itself — there is no deployed artefact for
another session to upgrade underneath it, and the in-session cases are already
covered by `daemon_restart_verifier` and `check-source-fresh`. The gap is real
only where `.claude/hooks-daemon/` is an installed clone that an upgrade
replaces.

So the handler reads `daemon.self_install_mode` (`config/models.py:1576`) and is
dormant when true, via `CanBeDormant` (Plan 00390) so a self-install project's
generated `CLAUDE.md` does not announce it as active policy either.

## SETTLED — where the check runs

**UserPromptSubmit.** Once per user turn: cheap enough to need no gate, catches
the mid-session case that motivated the plan, and puts the advisory where the
agent actually reads it. Rejected alternatives, recorded:

- **On hook dispatch** — many times per turn for a fact that changes at most
  once per upgrade. All cost, no extra coverage.
- **SessionStart only** — a session already in flight never re-checks, which is
  exactly the reported case.
- **Writer announces** (`scripts/upgrade.sh` signals running daemons) — exact
  and nearly free, but only covers upgrades run through that script. Worth
  revisiting as a complement, not as the primary.

## The signal — no startup bookkeeping needed

The handler runs INSIDE the daemon process, so the version the process imported
IS its startup state. No controller change is required:

```text
in-memory  claude_code_hooks_daemon.version.__version__   what this process loaded
on-disk    .daemon-metadata.json -> daemon_version        what is installed NOW
```

Resolve the CURRENT venv with `resolve_existing_venv_python()` rather than
`sys.prefix` — after a fingerprint-keyed upgrade the running process's own
prefix still points at the OLD venv, whose metadata may be untouched. Read it
with the existing stdlib reader. Normalise the `v` prefix and tolerate the
`vX.Y.Z+<ref>.<sha>` guarded-branch form.

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

- [x] ✅ **Task 1.1**: Placement and scope RULED by the owner: UserPromptSubmit,
  and dormant in self-install mode because the check is only relevant to a
  client project with an installed clone.

### Phase 2: Build

- [x] ✅ **Task 2.1**: `TestReReResolvesTheVenvEachCall` drives the SAME handler
  instance across two calls, adding the new fingerprint-keyed venv only between
  them, so a cached-path implementation genuinely fails it.
- [x] ✅ **Task 2.2**: `TestReportsStaleWhenMetadataRewrittenInPlace` — same venv
  directory, `.daemon-metadata.json` rewritten with a new `daemon_version`.
- [x] ✅ **Task 2.3**: Implemented on `read_daemon_metadata` and
  `resolve_existing_venv_python`. No second metadata reader.
- [x] ✅ **Task 2.4**: `TestAdvisoryContent` pins both versions plus
  `daemon_cli_command("restart")`; the handler only ever returns text.
- [x] ✅ **Task 2.5**: `TestFailOpen` — no venv, no metadata, malformed, empty,
  and an uninitialised `ProjectContext` all ALLOW silently.
- [x] ✅ **Task 2.6**: Dormant when `daemon.self_install_mode` is true, via
  `CanBeDormant`. Verified in production, not just in test: after a daemon
  restart `grep daemon_upgrade_detector CLAUDE.md` returns nothing.
- [x] ✅ **Task 2.7**: `TestMatchingVersionIsSilent` — a matching version
  produces `context == []`, not merely a quieter message.

## Success Criteria

- [x] In self-install mode the handler is silent and is not announced as active
  policy in the generated `CLAUDE.md`. Verified on the running daemon, not only
  in test: after a restart, `grep daemon_upgrade_detector CLAUDE.md` returns
  nothing.

- [x] An unchanged version produces no output at all — `context == []`, not a
  quieter message.

- [x] A running daemon whose installed version changed reports itself stale
  without being asked, on the next UserPromptSubmit.

- [x] It reports stale when the upgrade created a NEW venv, proven by a test
  that drives ONE handler instance across two calls, so a remembered-path
  implementation fails it rather than passing on a fresh construction.

- [x] The advisory names the restart command and nothing restarts itself; the
  handler only ever returns text.

- [x] A missing, empty, malformed or unparseable metadata file allows the hook
  through, as does an uninitialised `ProjectContext`.

- [x] Every release-bound consequence is in the pending-release holding area:
  release note `40-a-running-daemon-notices-its-own-upgrade.md` and a
  `config-changes` entry. No truth-change entry, and the journal records why —
  this is additive, so no documented truth becomes false.

- [ ] Full QA passes and CI is green. Full QA 29/29 PASSED locally on the
  content of `f912c15b`; CI on that sha is pending.

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
