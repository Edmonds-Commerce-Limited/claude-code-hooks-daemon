# Release Process

**ALWAYS use `/release` skill. NEVER manually tag, edit CHANGELOG.md, or edit RELEASES/\*.md.**

## 🚨 A RELEASE IS HUMAN-GATED (ABSOLUTE, READ BEFORE ANYTHING ELSE)

**A release may ONLY begin when a human invokes `/release` in the CURRENT session.
An agent must never start, resume, or complete a release on its own initiative.**

### Why — this is not ceremony

**A release is a decision about SCOPE, and scope is not visible from inside the
repository.** The human decides which work belongs in a bundle. An agent can see
that the tree is clean, that QA is fully green, and that a version is bumped — and from
that it can see nothing at all about whether the intended bundle is complete.
There may be work not started, work in another session, work not yet described to
you. Cutting a release early does not just publish sooner: it strands the rest of
the bundle behind a version boundary and forces an unplanned follow-up release.

"The gates all passed" is therefore NOT authorisation. The gates check that a
release *would be sound*, never that it is *wanted now*.

### The rule

| Situation                                                                  | Allowed to tag/publish?       |
| -------------------------------------------------------------------------- | ----------------------------- |
| Human invoked `/release` in this session and confirmed the publish step    | YES                           |
| Release state file records an explicit publish authorisation (see below)   | YES — resume and finish       |
| Release state file exists but records no publish authorisation             | Finish the prep, then **ASK** |
| A cron tick, failsafe-recovery wake-up, or `/loop` iteration fires         | **NO**                        |
| All blocking gates just went green and no state file authorises publishing | **NO — stop and ask**         |
| The working tree looks "ready" and a version bump is already committed     | **NO**                        |
| A plan or TODO says "finish the release"                                   | **NO**                        |

### A release MAY span a compaction — and then it MUST be finished

Releases are long. A compaction part-way through one is normal, not an anomaly,
and **abandoning a half-finished release is its own broken state**: the version
is bumped, `UNRELEASED/` task and manifest directories have been moved, the
changelog and release notes are written, and nothing is tagged. Leaving that
sitting in the tree is worse than either finishing or reverting it.

So the two failure modes are symmetric, and both are real:

- **Fabricating authorisation** — an agent decides a release is wanted because
  the tree looks ready. This publishes work the human never agreed to bundle.
- **Losing authorisation** — an agent drops a genuinely authorised release
  because a compaction ate the instruction. This strands the tree mid-release.

**Neither is solved by remembering harder.** Authorisation and progress must be
recorded WHERE A COMPACTION CANNOT REACH — on disk, not in context.

### The release state file

`/release` MUST write `untracked/release-state.json` as its first action, and
update it as each numbered step completes:

```json
{
  "version": "3.52.0",
  "authorised_by_human_at": "<ISO timestamp of the /release invocation>",
  "publish_authorised": false,
  "last_completed_step": 8,
  "notes": "human confirmed scope: plans 00197-00202 + 00206"
}
```

Rules for reading it:

- **No state file ⇒ no release is in progress.** A dirty tree, a bumped
  version, or a plan saying "finish the release" is NOT a substitute. Ask.
- **State file present ⇒ a release IS authorised.** Resume from
  `last_completed_step`; do not restart it and do not re-litigate whether it
  should happen.
- **`publish_authorised` gates Steps 14–15 only.** Prep steps are reversible and
  may proceed on the file's authority alone. Tag and publish are outward-facing
  and effectively irreversible — once pushed, other installations upgrade onto
  them. Set this flag only from an explicit human "yes, publish", never from
  the fact that the gates passed.
- **Delete the file** once Step 15 verification succeeds, so a later session
  cannot mistake a finished release for an in-flight one.

The scope question — "is the bundle complete?" — is the one thing an agent
cannot answer from the repository, which is why `notes` records the human's
answer rather than the agent's inference.

**Steps 14 and 15 (tag, GitHub release) are the hard gate.** Preparing a release
— version bump, changelog, release notes, running QA — is reversible and may
proceed under `/release`. Tagging and publishing are outward-facing and
effectively irreversible: once pushed, other installations upgrade onto them.
Ask before those steps, every time, even inside an authorised `/release` run.

**If in doubt, stop and ask.** An unwanted release costs a forced follow-up
version and a broken bundle. A delayed release costs minutes.

### Recovering from an unauthorised release

Do NOT silently unpublish — that is a second unilateral outward-facing act. Tell
the human what was published and let them choose between leaving it (the next
bundle simply becomes the following version) and withdrawing it:

```bash
# ONLY on explicit human instruction:
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
gh release delete vX.Y.Z --yes
```

## Prerequisites

- Clean git state, all QA passing
- `gh auth status` authenticated
- Write access to GitHub repository

## Quick Release

```claude-code
/release          # auto-detect bump
/release 2.2.0   # explicit version
/release patch    # bump type
```

## Pipeline Overview

```
1.  Pre-Release Validation (Agent)
2.  Version Detection
3.  Version Update (Agent)
4.  Changelog Generation (Agent)
5.  Release Notes Creation (Agent)
6.  Move UNRELEASED Post-Upgrade Tasks   <- BLOCKING
7.  Opus Documentation Review
8.  QA Verification Gate                 <- BLOCKING
9.  Breaking Changes Check               <- BLOCKING
10. Code Review Gate                     <- BLOCKING
11. CLAUDE.md Guidance Audit             <- BLOCKING
12. Acceptance Testing Gate              <- BLOCKING
13. Commit & Push
14. Tag & GitHub Release
15. Post-Release Verification
```

**ANY blocking gate failure = ABORT release immediately. No exceptions.**

Agents cannot spawn nested agents. Main Claude orchestrates by invoking agents sequentially.

## 🚨 Review Early, Never Drop Findings (Plan 00157)

The Code Review Gate (Step 10) and CLAUDE.md Guidance Audit (Step 11) currently
run **after** the QA (Step 8) and just **before** the Acceptance gate (Step 12).
That ordering has a cost: any fix applied to a review finding forces a full
FAIL-FAST restart of the QA + acceptance gates (code changes can regress earlier
tests). So **blocking** findings are expensive to fix in place, and there is
pressure to defer **non-blocking** findings — which risks losing review value as
silent tech debt.

Two non-negotiable rules close that gap:

1. **Prefer reviewing early.** When practical, run the code review + guidance
   audit against the diff *before* the QA/acceptance gates, so findings can be
   fixed and re-verified in one pass rather than triggering a downstream
   FAIL-FAST re-run.
2. **Never drop a finding.** Every review finding is either (a) fixed before the
   release ships, or (b) captured as a tracked MUST-FIX item in a follow-up plan
   (`CLAUDE/Plan/NNNNN-*`) with file:line, severity, and remediation, and fixed
   **immediately after** the release to close the loop. A review whose findings
   evaporate into scrollback is wasted work.

## 🚨 Absolute Paths Only (NON-NEGOTIABLE)

**Every command in the release flow MUST use absolute paths. NEVER `cd` into a subdirectory.**

The Bash tool's working directory **persists between calls**. A single `cd` (e.g. into `untracked/release-artifacts/` for a checksum loop) silently breaks every later relative-path command — `git tag -F RELEASES/vX.Y.Z.md`, `git push origin vX.Y.Z`, and `gh release create ... untracked/release-artifacts/*.sh` all resolve against the wrong cwd and fail with `could not open ...`, `src refspec does not match any`, or `no matches found`. This shipped a half-broken release attempt in v3.17.0 (main pushed, tag + GitHub release silently skipped) before it was caught.

Rules:

- Use `/workspace/...` absolute paths for ALL file arguments: `git tag -a vX.Y.Z -F /workspace/RELEASES/vX.Y.Z.md`, `gh release create ... /workspace/untracked/release-artifacts/upgrade.sh`, etc.
- If a step needs a different directory, prefer `git -C /workspace ...` or absolute paths over `cd`. If you must `cd`, immediately `cd /workspace` afterwards in the SAME command, and verify `pwd` before the next git/gh step.
- After tag + release creation, VERIFY with ground-truth checks (`git tag -l vX.Y.Z`, `git ls-remote --tags origin vX.Y.Z`, `gh release view vX.Y.Z`) — non-zero exit or empty result = the step failed; do not trust scrollback.

---

## Steps 1-5: Agent-Automated

### 1. Pre-Release Validation

Agent verifies: clean git state, all QA passes, version consistency across files (pyproject.toml, version.py, README.md), no existing tag, gh CLI authenticated. (`CLAUDE.md` carries no version string — it is a daemon-regenerated doc, not a version-bump target.)

**ANY failure = IMMEDIATE ABORT. NO auto-fixing.**

### 2. Version Detection

Auto-detects from commits since last tag:

- **PATCH**: fix/bug/docs/refactor keywords
- **MINOR**: feat/Add/Implement keywords
- **MAJOR**: BREAKING/incompatible keywords

Agent proposes bump with justification. Manual override accepted.

### 3. Version Update

Updates version in: `pyproject.toml`, `version.py`, `README.md` (badge), and `.claude/ccy/claude-supervise.py` (the standalone supervisor's hardcoded `__version__`, kept in lockstep — enforced by `tests/unit/supervise/test_compaction_gap_repro.py::TestSupervisorVersionMatchesDaemon`, which FAILS the QA gate if the supervisor version drifts from `version.py`).

Also check README.md's stats still hold. Both the badge and the body state a
deliberately ROUNDED test figure ("12,000+"), which stays true across many
releases — update it only when the real count crosses the next round number,
not every release. README carries no handler count and no event-type count, so
there is nothing to sync from `.claude/HOOKS-DAEMON.md`; an earlier version of
this step named both, sending the reader hunting for figures that are not
there.

**Regenerate `.claude/HOOKS-DAEMON.md` after the version bump**: run `./bin/hooks-daemon generate-docs`. This tracked, generated doc embeds the daemon version in its header (`> Generated on YYYY-MM-DD (vX.Y.Z) …`), so without regenerating it the header ships stale one version behind (v3.43.1 shipped with a v3.43.0 header before this step existed). Stage `.claude/HOOKS-DAEMON.md` with the release commit (add it to the Step 13 `git add` list).

**Re-lock `uv.lock` after the `pyproject.toml` version bump** (self-install mode tracks `uv.lock`): run `uv lock`. The dependency QA check runs `uv lock --check` and will FAIL the Step 8 gate with a lockfile-out-of-date error until the lock is regenerated. Stage `uv.lock` with the release commit.

### 4. Changelog Generation

[Keep a Changelog](https://keepachangelog.com/) format with Added/Changed/Fixed/Removed sections. Parses commits since last tag, groups by prefix, highlights BREAKING and SECURITY.

### 5. Release Notes

Creates `RELEASES/vX.Y.Z.md` with: summary, changelog, upgrade instructions (if breaking), install/upgrade commands, test stats, contributor list, comparison link.

---

## Step 6: Move UNRELEASED Post-Upgrade Tasks (BLOCKING)

**Context**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` accumulates task files written during the release cycle (audits of prior-version bugs, config-migration guidance, workflow-change notifications, etc.). At release time these MUST be moved into the versioned upgrade guide so upgrading users see them.

**See**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md` for the convention and schema.

### What to check

```bash
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
```

| State                           | Action                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Only `README.md` present        | Nothing to move. Delete `post-upgrade-tasks/` from the versioned upgrade guide if one was scaffolded. |
| `NN-*.md` task files present    | Move them (steps below). Do NOT leave them in `UNRELEASED/`.                                          |
| Versioned upgrade guide missing | **ABORT** — create it from `CLAUDE/UPGRADES/upgrade-template/` first (see Step 9).                    |

### How to move

Target: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/`.

```bash
TARGET="CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks"
mkdir -p "$TARGET"

# Copy the per-release index README (if not already present)
cp CLAUDE/UPGRADES/upgrade-template/post-upgrade-tasks/README.md "$TARGET/README.md"

# Move each task file — use git mv so history follows
git mv CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md "$TARGET/"
```

### Populate the per-release task index

Edit `$TARGET/README.md`:

1. Update the heading: `# Post-Upgrade Tasks — vPREV → vNEW`
2. Replace the placeholder task-index table with one row per moved task, ordered by filename. Each row: `| file | type | severity | applies-to | one-line summary |`.
3. Delete the `00-EXAMPLE-task.md` reference — that file only belongs in the template.

### Verify

```bash
# UNRELEASED should contain only README.md
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
# Expected: README.md  (nothing else)

# Versioned guide should list every moved task
cat CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/README.md
# Expected: task index populated, no placeholder rows, no 00-EXAMPLE reference
```

### Reference from release notes

If any moved tasks have `Severity: critical` or `recommended`, `RELEASES/vX.Y.Z.md` MUST reference the post-upgrade-tasks directory so upgrading users know to read it:

```markdown
## Post-Upgrade Tasks

After upgrading, review `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/` — it contains [N] task(s) that may require action in your project (e.g. auditing files damaged by prior-version bugs, adapting to changed defaults).
```

**ABORT condition**: any `NN-*.md` file remains in `UNRELEASED/post-upgrade-tasks/` when moving to the next step.

### Move UNRELEASED truth-changes

Truth-changes (Plan 00118) record statements that **were true** about working in a project but became false this release (a `was → now` doc-reconciliation list consumed by `upgrade.md` and `check-truth-changes`). Any staged in `UNRELEASED/truth-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged truth-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/truth-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/truth-changes/
done
```

Verify only `README.md` remains under `UNRELEASED/truth-changes/`:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/truth-changes/
# Expected: README.md  (nothing else)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/truth-changes/` when moving to the next step.

### Move UNRELEASED config-changes

Config-changes (Plan 00133) is the per-version manifest of `added` / `renamed` / `removed` / `changed` config keys, consumed by `upgrade.md` and `check-config-migrations` to surface new + recommended options on upgrade. Any staged in `UNRELEASED/config-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged config-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/config-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/config-changes/
done
```

**Then set `date:` in each moved manifest** to today's release date in ISO 8601
form (`YYYY-MM-DD`). A staged manifest is drafted with `date: "UNRELEASED"`
because the release date does not exist yet; the move is the moment it becomes
knowable. Nothing reads this field at runtime — `ConfigMigrationManifest` parses
it into an attribute that is never rendered or compared — so a forgotten
placeholder is completely silent, and four shipped manifests carried one before
`check_repo_hygiene`'s `unreleased-manifest-date` rule was added to catch it.

Verify only `README.md` remains under `UNRELEASED/config-changes/`, and that no
live manifest still carries the placeholder:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/config-changes/
# Expected: README.md  (nothing else)

grep -l 'UNRELEASED' CLAUDE/UPGRADES/config-changes/v*.yaml
# Expected: no output (the Step 8 QA gate enforces this too)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/config-changes/` when moving to the next step.

---

## Step 7: Opus Documentation Review

Opus reviews **documentation only** (not code/QA):

- Version numbers consistent across files
- README.md stats updated
- Changelog accurate and categorized
- Release notes comprehensive
- Security/breaking changes marked
- Upgrade instructions clear
- `UNRELEASED/post-upgrade-tasks/` contains only `README.md` (all tasks moved in Step 6)
- Moved tasks have populated the versioned guide's `post-upgrade-tasks/README.md` task index
- Release notes reference post-upgrade tasks if any are `critical` or `recommended`
- **Did this release change a documented truth?** (a workflow, command, or convention a project's own docs are likely to assert) — if so, a `truth-changes/v{X.Y.Z}.yaml` entry exists (`was → now`, or `now: ~` to retire it) and `UNRELEASED/truth-changes/` contains only `README.md`
- **Did this release add an opt-in feature or flip a default?** (a feature that would otherwise ship dormant in client projects) — if so, a `config-changes/v{X.Y.Z}.yaml` entry exists with `recommended: true` (and `recommended_value:` for a default flip) so the upgrade advisory actively promotes enabling it, and `UNRELEASED/config-changes/` contains only `README.md`

Approved -> proceed. Issues found -> agent fixes docs, re-submit until approved.

---

## Step 8: QA Verification Gate (BLOCKING)

Main Claude runs: `./scripts/qa/llm_qa.py all`

Every check the script runs must pass. ANY failure = ABORT.

The script is the single source of truth for which checks exist — do not
restate the count here. It previously said "10" while the suite ran 13.

---

## Step 9: Breaking Changes Check (BLOCKING)

**Context**: v2.11 and v2.12 shipped breaking changes without upgrade docs.

### Detection

Scan the new CHANGELOG.md entry for:

1. Any entries in "Removed" section
2. "BREAKING" keyword in "Changed" section
3. Keywords: "BREAKING", "breaking change", "incompatible", "renamed"
4. New `@abstractmethod` on `Handler` base class in `core/handler.py`
   - If found: `_ABSTRACT_METHOD_VERSIONS` in `project_loader.py` must include it
   - Upgrade guide must document: method name, version, stub to add, detection via `validate-project-handlers`

### Decision

| Breaking Changes? | Upgrade Guide Exists? | Action                         |
| ----------------- | --------------------- | ------------------------------ |
| Yes               | Yes                   | Proceed                        |
| Yes               | No                    | **ABORT** - create guide first |
| No                | N/A                   | Proceed                        |

### Upgrade Guide Requirements

Location: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/`

Template: `CLAUDE/UPGRADES/upgrade-template/`

Must include: summary, version compatibility, pre-upgrade checklist, changes overview, step-by-step instructions, verification steps, rollback instructions.

Release notes MUST reference upgrade guide with BREAKING CHANGES section.

---

## Step 10: Code Review Gate (BLOCKING)

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
git log --oneline "${LAST_TAG}..HEAD"
git diff "${LAST_TAG}..HEAD" -- src/
```

Review checklist:

- No bugs in `matches()`/`handle()` logic
- No security anti-patterns
- Priority ranges correct (see the [Priority Guide](../HANDLER_DEVELOPMENT.md#priority-guide))
- Tests exist for every handler change
- Named constants (no magic values), SOLID principles
- No debug code, workarounds, or leftover TODOs

Issues found = ABORT, fix, re-run `/release`.

---

## Step 11: CLAUDE.md Guidance Audit (BLOCKING)

**This step is now a gate, not a sub-agent sweep** (Plan 00203). Coverage of
`get_claude_md()` is enforced continuously by
`tests/integration/test_claude_md_guidance_coverage.py`, which enumerates every
handler and fails unless each carries a recorded verdict — covered, or exempt
with a reason. Step 8's QA run already executes it, so if Step 8 passed, this
gate has passed.

Confirm explicitly:

```bash
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
"$PY" -m pytest tests/integration/test_claude_md_guidance_coverage.py -q
```

**Why the sweep was replaced.** The v3.52.0 release ran the sub-agent audit and
reported six PreToolUse *advisory* handlers returning `None`. Plan 00203 then
applied a written criterion to all 107 handlers and found **all six were
correct** — while two handlers the audit had not looked at were genuinely
missing guidance: `lint_on_edit` (PostToolUse, and it DENIES) and
`hedging_language_detector` (Stop, whose identical twin was covered). A sweep
scoped to one event type cannot find either, and re-derives the same verdicts
by hand every release. The table records them once.

**If the gate fails**, it names the handler and what to do. Apply the four
tests in `CLAUDE/HANDLER_DEVELOPMENT.md`, then either implement
`get_claude_md()` or record the exemption with its reason. If you change
`src/`: run QA, restart the daemon, update the changelog, and make sure Step 13
stages the source file — the daemon auto-commits the regenerated `CLAUDE.md`,
so a guidance fix can otherwise ship as a generated artifact with no source
behind it.

---

## Step 12: Acceptance Testing Gate (BLOCKING)

**Delegation is governed by each test's `Requires Main Thread` field in the
generated playbook** (see the playbook's "Execution Routing" section). A test
marked `yes` must NEVER be delegated — lifecycle events and this session's
system-reminders genuinely cannot be observed from a sub-agent, which is the
enduring lesson of the v2.9.0 incident (async sub-agent testing created race
conditions). Tests marked `no` may be delegated to parallel sub-agents —
verified experimentally: sub-agents ARE blocked by PreToolUse hooks and DO see
PostToolUse system-reminders in their own context. Batch delegable tests by
the playbook's `Recommended Model` field for speed.

### Scope

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
HANDLER_CHANGES=$(git diff "${LAST_TAG}..HEAD" --name-only -- src/claude_code_hooks_daemon/handlers/)
```

| Bump        | Handler Changes? | Action                              |
| ----------- | ---------------- | ----------------------------------- |
| MAJOR/MINOR | Any              | Full suite                          |
| PATCH       | Yes              | Targeted tests for changed handlers |
| PATCH       | No               | Skip — document in release notes    |

### Execution

**Step 12.0** (H-1 deterministic install/diagnostic gates — Plan 00104 Phase 9
Task 9.6 + Plan 00105 Phase 1): Run BOTH deterministic acceptance gates that
exercise the production install path and the production diagnostic scripts
end-to-end against a fresh fixture project. Together they catch:

- The v3.9.x regression class — `write-venv-metadata` writing the system
  interpreter as `python_path`, `daemon-cli.sh` / `health-check.sh` crashing
  with `ModuleNotFoundError`, skill `upgrade.sh` self-bootstrap silently
  falling back on network failure.
- The v3.10.0 SEV-1 class — `print_info` writing to stdout corrupting every
  `VAR=$(ensure_venv ...)` capture, breaking every upgrade in the field.
- Any future bug in `install_version.sh` → `ensure_venv` → `verify_venv` →
  `write-venv-metadata` → daemon-start that produces a non-running daemon.

```bash
# pytest needs the daemon's venv interpreter. Resolve it through the CANONICAL
# resolver — never hand-roll a venv path, and never assume the shell exports an
# interpreter variable (python-var-guidance-exempt: $PYTHON is named here as the
# banned pattern to warn against — no agent shell ever sets it; Plan 00192).
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
"$PY" -m pytest tests/acceptance/test_diagnostic_scripts.py tests/acceptance/test_install_sh_end_to_end.py tests/acceptance/test_tool_use_error_recovery.py tests/acceptance/test_stop_hook_hard_block.py tests/acceptance/test_skill_install_python_discovery.py -v
# Expected: tests/acceptance/test_diagnostic_scripts.py — 12 passed
#           tests/acceptance/test_install_sh_end_to_end.py — 2 passed
#           tests/acceptance/test_tool_use_error_recovery.py — 1 passed, 1 skipped
#           tests/acceptance/test_stop_hook_hard_block.py — 3 passed
#           tests/acceptance/test_skill_install_python_discovery.py — 4 passed
#           combined: 22 passed, 1 skipped, 0 failed
```

**The one expected skip is `test_tool_use_error_recovery_branch_skipped_on_success`,
and ONLY while a release is in flight.** This repository's own terminal
`release_blocker` project handler sits at priority 8, ahead of
`auto_continue_stop` at 10, so during a release it answers first and the
default branch's wording cannot be observed over the socket. The test's real
assertion — Branch 2.5 must not fire on a clean turn — still executes; only the
question of which branch answered instead is unobservable. Its skip message
names the release explicitly, so read it rather than assuming: a skip here for
any OTHER reason is an abort condition (see below).

ANY failure in any file = ABORT release. The 2026-05-01 field report
(Issues #1, #4, #6) escaped because the v3.9.0 acceptance suite never invoked
the diagnostic scripts — only hook dispatch. The v3.10.0 SEV-1 escaped
because the v3.10.0 H-1 gate synthesised state via `write-venv-metadata`
directly instead of running the production `ensure_venv` capture chain. Both
gaps are closed by adding `test_install_sh_end_to_end.py` here. The Plan
00101 silent-stop recurrence (Edit-on-unread-file → tool_use_error → no
recovery) is closed by adding `test_tool_use_error_recovery.py` — exercises
the `auto_continue_stop` Branch 2.5 directly against the live daemon socket.
The Plan 00101 Phase 9 suggestion-level-downgrade regression class
(v2.1.114 silently demoting JSON-stdout `decision=block` to
`level: suggestion, preventedContinuation: false`) is closed by adding
`test_stop_hook_hard_block.py` — invokes the production bash wrappers
`.claude/hooks/stop` and `.claude/hooks/subagent-stop` as subprocesses
and asserts the exit-2 + stderr contract that v2.1.114 honours for hard
re-entry. The test skips cleanly when no daemon is running locally; under
H-1 the daemon is always started before this step, so a skip for THAT
reason is itself an abort condition — distinct from the release-in-flight
skip described above, which is expected. Always read the skip message
rather than counting skips. The Plan 00110 host-a field-report regression
class (host has `python3` → 3.9 alongside `python3.13` / `python3.14`, but
pre-Plan-00110 install.sh aborted with a hardcoded `python3.11` suggestion
that the host did not have) is closed by adding
`test_skill_install_python_discovery.py` — invokes the production
`src/.../skills/hooks-daemon/scripts/install.sh` against synthesised PATH
layouts and asserts (a) the host-a scenario auto-selects `python3.14`
without operator help, and (b) the failure diagnostic NAMES the observed
`python3.9 (3.9.21)` interpreter instead of a hardcoded suggestion that
may not exist on the host.

**Step 12.1**: Restart daemon, verify RUNNING.

**Step 12.2**: Verify OBSERVABLE handlers in system-reminders (SessionStart, UserPromptSubmit, PostToolUse).

**Step 12.3**: Generate playbook: `./bin/hooks-daemon generate-playbook > /tmp/playbook.md`

**Step 12.4**: Execute the playbook's tests, routing each by its
`Requires Main Thread` field (see the Step 12 intro):

- **BLOCKING tests**: Bash/Write/Edit with dangerous commands, verify hook denies
- **ADVISORY tests**: Verify system-reminder shows context
- **Skip**: Untriggerable lifecycle events (verified by daemon load + unit tests)

The generated playbook is the single source of truth for which tests exist and
how many — do not restate counts here. This section previously hardcoded
"~65 blocking / ~24 advisory" while `generate-playbook` was emitting over 200
tests.

**Step 12.5**: All tests must pass. Failed = 0.

### FAIL-FAST Cycle

1. STOP testing immediately
2. Fix bug with TDD
3. Run full QA: `./scripts/qa/llm_qa.py all`
4. Restart daemon
5. **RESTART ALL tests from Step 12.1** (code changes can regress earlier tests)
6. Repeat until zero failures

---

## Step 13: Commit & Push

### 🚨 Stage source changes too — the file list below is NOT sufficient

**Steps 10 (Code Review) and 11 (CLAUDE.md Guidance Audit) are both expected to
modify `src/`.** Step 11 exists precisely to fix `get_claude_md()` bodies. The
`git add` list below names only version/doc artifacts, so a guidance fix is
silently left uncommitted unless you stage it explicitly.

**Why this is silent and dangerous**: the daemon's own auto-commit hook commits
the *regenerated* `CLAUDE.md` on restart. So the GENERATED artifact lands in
git while its SOURCE handler does not. The tagged tree then ships resident
CLAUDE.md guidance that no handler in that tree produces — and the next
`generate-docs` or daemon restart in any client project silently reverts it.
This was caught by the Opus gate during v3.49.1; it would otherwise have
shipped.

**Always run this before staging** and add anything it reports:

```bash
git status --porcelain -- src/ scripts/ tests/
```

```bash
git add pyproject.toml version.py README.md CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md \
  .claude/HOOKS-DAEMON.md uv.lock .claude/ccy/claude-supervise.py \
  CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/ \
  CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
# Plus EVERY src/, scripts/ and tests/ path reported above (Steps 10/11 edits).
git commit -m "Release vX.Y.Z: [Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
git push origin main
```

**Verify nothing was left behind before tagging** — a non-empty result means a
Step 10/11 source edit did not make it into the release commit. Fix and amend
BEFORE Step 14; once tagged, the divergence is published:

```bash
git status --porcelain -- src/ scripts/ tests/
# Expected: empty.
```

## Step 14: Tag & GitHub Release

The release bundle MUST include `bootstrap-checksums.txt` alongside ALL FOUR
self-bootstrapping skill scripts: `upgrade.sh`, `daemon-cli.sh`,
`health-check.sh`, and `init-handlers.sh`. Each script's self-bootstrap stanza
(Plan 00104 Task 5.1 Decision 3.C + Plan 00105 Phase 4 Decision 3.B)
downloads the manifest, looks up its own basename, sha256-verifies its own
body, and aborts the run if either is missing or inconsistent. Skipping any
of these four artifacts ships a release that every existing installation
refuses to run for that script — every diagnostic invocation aborts loudly
with `Error: bootstrap-checksums.txt has no entry for <basename>`.

**Note on `upgrade.sh` (Plan 00109)**: As of v3.15.0 the skill-pushed
`upgrade.sh` is a thin shim that fetches `scripts/upgrade.sh` from
`main` HEAD and execs it — it no longer carries a self-bootstrap stanza
and clients never run the published `upgrade.sh` artifact. The artifact
is still bundled here for cross-symmetry with the three sibling scripts
that DO still self-bootstrap against the manifest. Plan 00109 Decision 4
captures the rationale: removing `upgrade.sh` from the manifest would
require touching this loop and the manifest builder, with no upside
until the sibling-script thinning plan lands. Once the siblings are
thinned too, all four artifacts can be dropped together.

```bash
# Build the bootstrap manifest. List every artifact every self-bootstrap
# stanza may verify against — all four skill scripts.
mkdir -p untracked/release-artifacts
SKILL_SCRIPTS_DIR="src/claude_code_hooks_daemon/skills/hooks-daemon/scripts"
for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh; do
    cp "$SKILL_SCRIPTS_DIR/$script" "untracked/release-artifacts/$script"
done
scripts/release/build_bootstrap_checksums.sh \
   untracked/release-artifacts/bootstrap-checksums.txt \
   untracked/release-artifacts/upgrade.sh \
   untracked/release-artifacts/daemon-cli.sh \
   untracked/release-artifacts/health-check.sh \
   untracked/release-artifacts/init-handlers.sh

git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest \
  untracked/release-artifacts/upgrade.sh \
  untracked/release-artifacts/daemon-cli.sh \
  untracked/release-artifacts/health-check.sh \
  untracked/release-artifacts/init-handlers.sh \
  untracked/release-artifacts/bootstrap-checksums.txt
```

**Verification before continuing**:

```bash
# Every artifact must be reachable from the latest-release URL each
# self-bootstrap stanza uses, and every script's published sha must match
# its manifest entry. ABORT release if any curl fails or any sha mismatches.
BASE="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/latest/download"
curl -fsSL -o /tmp/_check.txt "$BASE/bootstrap-checksums.txt"
for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh; do
    curl -fsSL -o "/tmp/_check_$script" "$BASE/$script"
    PUBLISHED_SHA="$(sha256sum "/tmp/_check_$script" | awk '{print $1}')"
    MANIFEST_SHA="$(awk -v name="$script" '$2 == name {print $1; exit}' /tmp/_check.txt)"
    if [ -z "$MANIFEST_SHA" ]; then
        echo "ABORT: manifest has no entry for $script"; exit 1
    fi
    if [ "$PUBLISHED_SHA" != "$MANIFEST_SHA" ]; then
        echo "ABORT: published $script sha ($PUBLISHED_SHA) != manifest ($MANIFEST_SHA)"; exit 1
    fi
done
# All four matched: release is internally consistent.
```

## Step 15: Post-Release Verification

```bash
git tag -l vX.Y.Z
gh release view vX.Y.Z --json tagName,isDraft,isPrerelease,url \
  --jq '{tag: .tagName, draft: .isDraft, prerelease: .isPrerelease, url: .url}'
# Expected: draft=false, prerelease=false
```

---

## Rollback

| State                    | Action                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| Before commit            | `git restore .`                                                                            |
| After commit, not pushed | `git reset HEAD~1`                                                                         |
| After push               | Create immediate patch release (NEVER force-push tags)                                     |
| Tag created              | `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z && gh release delete vX.Y.Z --yes` |

## Manual Release (Bypass Skill)

```bash
# 1. Edit versions: pyproject.toml, version.py, README.md
# 2. Update CHANGELOG.md (Keep a Changelog format)
# 3. Create RELEASES/vX.Y.Z.md
# 4. Move UNRELEASED/post-upgrade-tasks/NN-*.md into the versioned upgrade guide
#    and populate its post-upgrade-tasks/README.md task index
# 5. Run QA: ./scripts/qa/llm_qa.py all
# 6. Commit and push
# 7. Tag: git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z
# 8. gh release create vX.Y.Z --title "vX.Y.Z - [Title]" --notes-file RELEASES/vX.Y.Z.md --latest
```

## Semver Guidelines

| Level | When                                                                |
| ----- | ------------------------------------------------------------------- |
| PATCH | Bug fixes, security patches, docs                                   |
| MINOR | New handlers/features, config options, backwards-compatible         |
| MAJOR | Breaking API/config changes, removed features, Python version bumps |

No fixed schedule. Critical bugs = immediate patch. Features = minor when stable. Breaking = plan ahead.

## Related

- Skill spec: `.claude/skills/release/skill.md`
- Release agent: `.claude/agents/release-agent.md`
- QA pipeline: `CLAUDE/development/QA.md`
- Acceptance tests: `CLAUDE/AcceptanceTests/GENERATING.md`
