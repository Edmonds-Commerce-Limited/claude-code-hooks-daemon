# Plan 00217: supervisor deployed into client owned path

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client-repo field report found three ruff findings in the deployed
`claude-supervise.py` and correctly concluded that **none of them is a bug** —
all three are deliberate, documented design choices. The real finding is
structural, and it is ours:

**The daemon deploys daemon-owned source into a client-owned directory.**
`claude-supervise.py` lands in `.claude/ccy/`, which a client legitimately owns
and lints (it also holds their `Dockerfile`, `ccy.env` and project handlers).
The vendor path clients exclude by convention is `.claude/hooks-daemon/`. So
every client repo has ~3,100 lines of upstream code inside its Python tooling's
scope, and must independently rediscover why and write its own exclusion. It is
not alone: FOUR daemon-owned assets deploy outside the vendor directory, and
until this plan none of them declared that it was daemon-owned.

The trap closes on three sides, which is what makes it worth fixing rather than
documenting:

1. **Not fixable by the client** — `ccy.deploy_supervisor: true` (the
   recommended setting; `false` makes the running supervisor go stale, which
   `ccy_supervisor_integrity` itself warns about) refreshes the file on every
   upgrade, discarding any local edit.
2. **Not silenceable by the client** — the daemon's own `qa_suppression`
   handler denies a Write/Edit introducing `# noqa`, so an agent cannot even
   add a stopgap; a human must do it by hand and then lose it to (1).
3. **Not covered by the conventional exclusion** — the pattern that would work
   is not the one anybody writes by default.

The net effect is a finding that is simultaneously not a real defect, not
fixable, and not silenceable — the exact shape that erodes trust in a QA gate.

## Context & Background

- `REPORT.md` — the field report as received, kept as a supporting document.
- `EVIDENCE.md` — every measurement behind the decision below (reproductions,
  costs, and the two options that are mechanically self-defeating).

Reported against v3.51.0, ruff 0.16.2. The three findings: `BLE001` at line
2407 (a deliberate supervisory-boundary catch that preserves the traceback to a
file and substitutes a safe NOOP), and `DTZ005`/`DTZ006` at line 1907 (naive
local time, deliberate — the marker is read by a human scrolling their own
terminal history).

The mechanism, established from the code rather than assumed: ruff respects
`.gitignore` by default, and the production installer git-ignores
`.claude/hooks-daemon/`. No client ever wrote the "vendor exclusion" — git did
it for them. `install/ccy_supervisor.py` then deliberately whitelists
`!claude-supervise.py` back **out** of the ccy ignore so the file can be
committed (Plan 00147/00148), and that single act is what puts daemon-owned
source into every Python tool's discovery.

## Goals

- Make the ownership boundary **legible** — in the artifact and in the client
  docs — rather than moving the code. The original wording of this goal was
  "make the boundary match the directory layout"; Decision 1 rejects moving the
  file, because the vendor directory is git-ignored and a link or shim into it
  dangles for every teammate who clones, bricking the ccy launcher and
  disabling Plan 00164 stale detection.
- Ensure a client repo running default `ruff check .` gets no findings from
  daemon-owned files, and keep it that way with a guard covering EVERY such
  asset. (Measured: this was already true under ruff's real defaults — the
  reported findings need `BLE`/`DTZ` selected — but nothing asserted it.)
- Fix it once upstream rather than having every client rediscover and re-encode
  the same exclusion.

## Non-Goals

- **Changing the supervisor's behaviour.** The report is explicit that all three
  findings are correct as written and asks for no code change. Narrowing the
  `BLE001` catch would defeat its stated purpose; making the timestamps
  timezone-aware would make a human-facing terminal marker worse.
- Disabling or weakening `qa_suppression`. Its stance is right; the problem is
  that daemon-owned code is inside the client's lint scope at all.

## Tasks

### Phase 1: Choose the fix

- [x] ✅ **Task 1.1**: Evaluate the report's options against this project's
  conventions. All four were tested against the code rather than reasoned about;
  see `EVIDENCE.md` E1–E5 and Decision 1 below
- [x] ✅ **Task 1.2**: Note the tension in option (a) before choosing it. The
  tension turned out to be mechanical, not merely cultural: this repo selects
  `RUF` but not `BLE`/`DTZ`, so an upstream `# noqa` for those rules is itself a
  `RUF100` violation of our own gate (`EVIDENCE.md` E2)
- [x] ✅ **Task 1.3**: Record the decision with rationale under Technical
  Decisions

### Phase 2: Implement

- [x] ✅ **Task 2.1**: Implement the chosen fix with TDD
  - [x] ✅ Single manifest of daemon-owned assets deployed into client-owned
    paths (`install/client_owned_assets.py`), pinned to real files and to the
    client-facing document by `tests/unit/install/test_client_owned_assets.py`
  - [x] ✅ Ownership banner in EVERY deployed asset, not just the supervisor —
    none of the four carried one. For the 31 hook forwarders + status-line the
    banner lives in `install.py`'s generator and this repo's own `.claude/hooks/`
    was regenerated through that same code path
  - [x] ✅ Guard: `tests/integration/test_client_owned_asset_lint.py` — every
    manifest asset stays clean under its language's DEFAULT rule set
    (`ruff --isolated`, `shellcheck --norc`), the check that was absent
    (`CLAUDE.md` Core Standard 15)
- [x] ✅ **Task 2.2**: Verified against the client-shaped fixture, with BOTH a
  realistic client invocation (own `ruff.toml` selecting BLE+DTZ — reproduces
  the reported 3 findings, and only from the supervisor) and the isolated one
  (clean). Pasting the shipped exclusion verbatim returns it to clean; 39/39
  deployed files carry the ownership banner (`EVIDENCE.md` E8)
- [x] ✅ **Task 2.3**: Upgrade path confirmed — all four assets are redeployed
  by `upgrade_version.sh`, and the banner lives inside the copied bytes so the
  v3.24.0 class structurally cannot apply (`EVIDENCE.md` E9). Also surfaced a
  fixture gap: `dummy-client-repo` cannot run `upgrade_version.sh` at all,
  because its daemon dir is a git worktree and the script requires a `.git`
  directory

### Phase 3: Close the documentation gap

- [x] ✅ **Task 3.1**: State the ownership boundary explicitly where a client
  will read it — `CLAUDE/LLM-INSTALL.md` now carries "Which Files Under
  `.claude/` Are Yours?": the enumerated path list, why each file cannot live in
  the vendor dir, and the copy-pasteable ruff/shellcheck exclusions
- [x] ✅ **Task 3.2**: The supervisor does NOT move, but a documented truth still
  changed and client docs are likely to assert it — "the daemon lives in
  `.claude/hooks-daemon/`; everything else under `.claude/` is yours". Appended
  a third entry to `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.53.0.yaml`
  naming all four additional daemon-owned paths and the default-clean contract.
  Also added post-upgrade task `02-review-daemon-owned-file-banners.md`, since
  the upgrade rewrites ~39 committed files with a comment-only diff

## Dependencies

- Related: Plan 00147 (ccy container workflow), which introduced
  `deploy_supervisor`.
- Related: Plan 00164, which added stale-running-supervisor detection and is why
  `deploy_supervisor: false` is not a viable client workaround.

## Technical Decisions

### Decision 1: Declare the boundary and guard the class — do not move, shim or suppress

**Context**: pick between the report's four options. Measurements in
`EVIDENCE.md`.

**Options considered**:

1. **(a) `# noqa` upstream** — REJECTED. Self-defeating: this repo selects `RUF`
   but not `BLE`/`DTZ`, so those directives are `RUF100` "unused noqa"
   violations of our own gate (E2). Enabling `BLE`+`DTZ` to legitimise them
   costs 136 findings across the tree. It also only ever covers today's ruff,
   and no other linter.
2. **(b) real file under `.claude/hooks-daemon/`, symlink/shim at `.claude/ccy/`**
   — REJECTED, and it is worse than it looks (E4). The installer git-ignores
   `.claude/hooks-daemon/`, so the link target is absent from the client's repo:
   every teammate who clones gets a dangling symlink and a failed `exec` — the
   exact brick `ccy_supervisor_integrity` exists to warn about. It would also
   make that handler's "not executable → `chmod +x`" advice wrong, and would
   permanently disable Plan 00164 stale-supervisor detection, which compares an
   on-disk fingerprint that a symlink makes incapable of diverging.
3. **(c) document the exclusion** — ADOPTED, but not as the sentence the report
   describes. See below.
4. **(d) `qa_suppression` default `exclude_paths`** — REJECTED as unnecessary,
   not as confused. The report proposes it as an ENABLER for (c), not a rival
   fix: it would let a client write option (c)'s suppressions *inline*, which
   the handler currently denies. That reading of the handler is correct. Two
   measurements settle it anyway (E3): the handler allows a client agent to
   write the per-file-ignores stanza into `ruff.toml`/`pyproject.toml` today —
   only the inline directive in the `.py` is blocked — so the documented route
   needs no exemption; and an inline directive would be discarded by the next
   upgrade regardless, which is the report's own blocker (1). (d) would unlock
   an action whose result does not survive.
5. **(e) drop the `.py` extension at the deploy site** (our own proposal, not in
   the report) — REJECTED (E5). Architecturally the cleanest: an extensionless
   executable leaves every Python tool's discovery at once. But `_arm_ccy_supervisor()`
   never overwrites an existing `CCY_CLAUDE_WRAPPER`, and `_is_armed()` matches
   the literal `claude-supervise.py`, so every armed client keeps pointing at a
   filename we stopped deploying. The reporter's own `ccy.env` is hand-edited to
   `--dry-run`, so even a "rewrite only lines we generated" migration would miss
   it. The rename bricks the client who filed the report.

**Decision**: adopt (c), upgraded from documentation to shipped, tested
artifacts, and treat the finding as a **class** rather than an instance:

- an ownership **banner in the deployed file itself**, so the answer to "is this
  file mine?" arrives with the file and refreshes on every upgrade by
  construction — deployment is a byte copy, so there is no second refresh path
  to forget (the v3.24.0 failure mode);
- a **single manifest** of daemon-owned assets deployed into client-owned paths,
  because the list previously existed only implicitly across four install
  modules — which is why there was nothing to document, test, or hand a client;
- a **guard** asserting each manifest asset stays clean under its language's
  DEFAULT rule set. Five such assets exist and all are clean today (E6); nothing
  asserted that, so the next one to drift would reach a client the same way.

**Where we disagree with the report**: its ranking is inverted. Its first
choice is the most expensive and breaks our own gate; its second regresses two
shipped safety features; its last — dismissed as "weakest" — is the only one
that is both safe and fleet-wide, provided it ships as an artifact rather than
a paragraph. Its fourth is fairly reasoned but is made moot by the route we
chose, which the handler already permits.

**What upstream cannot promise**: cleanliness under rules a client *chooses*.
Under ruff's actual defaults the file is already clean (E1) — the reported
findings need `BLE`/`DTZ` selected. So the honest contract is: we guarantee
default-clean and we hand you the exclusion for anything stricter.

## Success Criteria

- [ ] A default `ruff check .` in a client repo reports nothing from
  daemon-owned files, and a guard keeps it that way for every daemon-owned asset
  deployed into client-owned space — not just this one
- [ ] The supervisor's behaviour is unchanged — no narrowed catch, no
  timezone-aware terminal markers
- [ ] The fix survives an upgrade
- [ ] A client can tell which files under `.claude/` are theirs without guessing
- [ ] A client running stricter-than-default rules can copy the exclusion rather
  than derive it

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00217-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Field report received and filed as a tracked plan
- Phase 1 decision recorded, with the two options that break our own gate — `72e328d2`
- Manifest + client boundary document — `4f8ceb8a`
- Ownership banner in every deployed asset + default-rules lint guard — `8b87277e`
- Client-fixture before/after evidence; option (d) re-framed — `65503ff0`
- Truth-change + post-upgrade task — `b8356836`

**Remaining before this plan can close** (not doable from an isolated worktree,
and deliberately left to the merge owner):

1. Authoritative `./scripts/qa/llm_qa.py all` against the real project root.
   From the worktree, `smoke_test` cannot pass (it needs a live daemon socket
   for this project root) and every pytest route needs
   `PYTHONPATH=<worktree>/src` plus a symlinked venv.
2. Daemon restart verification (`./bin/hooks-daemon restart` → RUNNING).
3. Then flip the status, `git mv` into `Completed/`, and update the README row
   and statistics in that same commit.
