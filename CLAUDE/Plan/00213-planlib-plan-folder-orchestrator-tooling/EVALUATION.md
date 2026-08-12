# Evaluation: `planlib` proposal (Phase 1 of Plan 00213)

**Verdict: ADAPT** — accept the library (§3) on the daemon's existing deploy-asset
seam, behind config, defaulted off; treat the QA handler (§6) and test suite (§7)
as a separate follow-up plan rather than as "Phase 2" of this one, because they
are not actually delivered as code in the proposal, only sketched.

This document is the detailed record backing the "Technical Decisions" section
of `PLAN.md`. It exists per this project's own EXTRACT convention (Plan 00211):
durable detail belongs in a named supporting file, not inflating `PLAN.md`.

---

## 1. Independent re-verification (Task 1.1)

### 1.1 Method

The proposal's own verification table (`PROPOSAL.md` lines 13-22) makes three
claims about `_planlib.inc.bash` as concatenated from the fenced code blocks in
§3 (3.1 through 3.12 — §3.13 is prose only, no code block):

| #   | Claim                                                                                         | How to check                             |
| --- | --------------------------------------------------------------------------------------------- | ---------------------------------------- |
| 1   | `bash -n`, **stderr asserted empty** (not just exit code)                                     | run and capture stdout/stderr separately |
| 2   | `shellcheck -x -S style`, clean                                                               | run and capture output                   |
| 3   | every called function cross-referenced against every defined function, no dangling references | static cross-reference                   |

I extracted the 13 fenced ```` ```bash ```` blocks between `## 3. The generic core, complete` and `## 4. The canonical bootstrap` in document order with a small
Python script (no hand-editing, no `sed`), producing a 628-line, 26,932-byte
`_planlib.inc.bash`. This reproduces exactly what the proposal says it did
("blocks concatenated into one file").

### 1.2 Results — all three claims independently confirmed

```
$ bash -n _planlib.inc.bash > stdout.txt 2> stderr.txt; echo "exit=$?"
exit=0
stdout_bytes=0
stderr_bytes=0
```

```
$ shellcheck -x -S style _planlib.inc.bash
exit_code=0
(no output at any severity — style, info, warning, error all clean)
```

Function cross-reference (regex-based, all `plan_*` / `_plan_*` identifiers):
24 functions defined, 24 distinct identifiers referenced, **zero dangling
references** (every called name resolves to a definition in the same file) and
**zero unused** definitions (every defined function is called at least once
elsewhere in the file).

All three claims check out exactly as stated, including the specific detail the
proposal calls out as easy to get wrong (`bash -n`'s exit code is not
sufficient on its own — I verified stderr separately, and it actually is
empty).

### 1.3 Bonus: dynamic smoke test (not claimed by the proposal, done for extra confidence)

The proposal's stated verification is entirely static. I additionally sourced
the extracted library and exercised the pure/testable primitives it explicitly
designed for testability without a live agent/TTY:

- Double-sourcing guard: sourcing twice is a clean no-op (`PLANLIB_SOURCED`
  guard fires as documented).
- `_plan_fingerprint_present`: exact match succeeds; a **prefix** match
  (`SHA256:AA` against a listing containing `SHA256:AAA`) is correctly
  **rejected** — this is the specific correctness property the proposal calls
  out in its own comment (space-delimited match, no prefix collision).
- `_plan_strip_cr`: strips a trailing `\r`, leaves the rest intact.
- `_plan_find_repo_root`: correctly finds a marker file several directories
  below it, **and** correctly refuses to walk past a nested repo's own `.git`
  boundary to find an outer repo's marker (the exact incident class §1.1 of
  the proposal describes) — built a throwaway nested-repo fixture under
  `mktemp -d` and confirmed both the positive and the boundary-refusal case.

All passed. This is not part of the proposal's own claims, but it corroborates
that the code does what its comments say, not just that it parses cleanly.

### 1.4 A caveat the proposal is honest about but is easy to miss on a skim

`PROPOSAL.md` §1.4 lists **three** artefacts: (1) `_planlib.inc.bash`, (2) the
`plan_script_qa` handler, (3) `test-planlib.bash`. The verification table at the
top of the document, read carelessly, can look like it covers "the proposal."
It does not — it covers artefact (1) only, and the document is precise about
that scope ("The library in §3 ... blocks concatenated into one file").

Checking what's actually *present as code*:

- **Artefact 1 (library, §3)**: complete, 628 lines, verified above. ✅
- **Artefact 2 (`plan_script_qa`, §6)**: NOT a complete rule engine. What's
  actually there: one `is_orchestrator()` predicate (~10 lines), one regex for
  R7b (the subshell-leg static check), one "representative" implementation of
  R15's `_target_is_core()` predicate, and a **table** naming 15 rules (R1-R15)
  with no bodies. The two-file split (`_plan_script_rules.py` /
  `plan_script_qa.py`) is described, not written.
- **Artefact 3 (`test-planlib.bash`, §7)**: NOT present at all as code. §7 states
  four testing *principles* (pure predicates, assert-the-mechanism not just the
  exit code, negative-control perturbation, a stated TTY-coverage gap) with two
  illustrative assertion lines and one example manual-checklist block. No
  runnable test file exists in the document.

This matters directly for scoping any Phase 2: "adopt artefact 1" is a
drop-in of already-verified code. "Adopt the proposal" as a unit means writing
most of a rule engine and an entire test suite from a bullet list and a
15-row table — a materially different, much larger piece of work that this
project's own TDD discipline (RED before GREEN) would have to do from
scratch, because there is no RED to start from for artefacts 2 and 3.

### 1.5 §5 skeletons — confirmed non-executable, correctly excluded from the claim

Grepped `PROPOSAL.md` for the placeholder tokens: `<BOOTSTRAP>`, `<MARKER>`,
`<PLAN_DIR>`, `<cmd…>` all appear literally in the §4 bootstrap snippet and the
three §5 skeletons. They are genuinely templates, not scripts with unresolved
variables that merely look like placeholders. Their failure to run is not a
defect — consistent with the proposal's own framing.

---

## 2. Overlap with what the daemon already ships (Task 1.2)

| Existing daemon tooling                                                                                                                                                                 | What it actually does                                                                                                                                                                                                                                                                | Overlap with `planlib`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE/Plan/mkplan.bash` (384 lines, deployed by the installer)                                                                                                                        | Scaffolds a **new** plan folder: assigns the next number from a git-anchored counter, takes an exclusive lock, writes `PLAN.md` (+ optional `JOURNAL/`) from a template. One-shot, at plan **creation** time.                                                                        | **None functionally.** Different lifecycle stage entirely — plan creation vs. running a script that lives *inside* an existing plan folder. The only resonance is a shared engineering instinct: both resolve their "repo root" from the *script's own location*, never the cwd (`mkplan.bash` via `git -C "$plan_dir" rev-parse --show-toplevel` using an explicitly-passed directory; `planlib` via a filesystem walk that deliberately avoids `git rev-parse` entirely). Two independent implementations converging on "don't trust the cwd" — mild validation that `planlib`'s design instinct is sound, not evidence of duplication. |
| `deploy-plan-workflow` CLI / `bootstrap_plan_workflow()` (`install/plan_workflow.py`)                                                                                                   | Installer/upgrade-time asset deployment: copies `mkplan.bash` (daemon-owned, overwritten every run), seeds `_TEMPLATE_.md` and journal assets (client-owned, seed-once), gated on `plan_workflow.enabled` in config.                                                                 | **None functionally** — it is pure file-deployment plumbing, not a runtime capability. It is, however, **exactly the seam Plan 00213's own Goals section names** for landing `planlib` if accepted ("the deploy-assets path already used by `mkplan.bash`"). Confirmed this is a real, reusable, already-idempotent mechanism — not something that would need inventing.                                                                                                                                                                                                                                                                  |
| `plan_qa` check catalogue — 30 checks (`plan_qa/checks/*.py`) across 3 enforcement surfaces (`plan_qa_edit` PreToolUse, `plan_qa_commit_gate` PreToolUse, `plan_qa_sweep` SessionStart) | Every check inspects `PLAN.md` content, the README index, journal day-files, or git/commit metadata: status-line presence, task-marker grammar, header/body coherence, terminal-state archive moves, journal append-only/freshness, staleness, row/folder bijection, doc-size tiers. | **Zero overlap.** Nothing in this catalogue looks at executable content anywhere, let alone bash scripts. `planlib`'s proposed `plan_script_qa` (§6) — linting a script's *structural safety* (root-resolution shape, ssh-key-before-log ordering, change-gate presence, leg discipline, `BASH_SUBSHELL` misuse) — is a genuinely new axis the daemon does not check today. This is the proposal's one real "new capability" claim, and it holds up.                                                                                                                                                                                      |
| `error_hiding_blocker` → `ShellErrorHidingStrategy` (`strategies/error_hiding/shell_strategy.py`)                                                                                       | Blocks `\|\| true`, `\|\| :`, `set +e`, `&>/dev/null`, `>/dev/null 2>&1`, `trap '' ERR` in **any** `.sh`/`.bash` file, project-wide, at Write/Edit time.                                                                                                                             | **Partial, additive overlap** with `planlib`'s proposed R9 ("no error hiding … `2>/dev/null`, `\|\| true`"). The daemon's existing coverage is *broader in scope* (any shell file, not just plan orchestrators) but the exact pattern set differs slightly (a bare `2>/dev/null` without a paired stdout redirect isn't currently one of the six patterns). Not a gap `planlib` needs to fill from scratch — mostly already covered.                                                                                                                                                                                                      |
| `qa_suppression` (`strategies/qa_suppression/*_strategy.py`)                                                                                                                            | Blocks language-specific suppression directives (Python `noqa`, Rust `#[allow(...)]`, etc.) — **no `shell_strategy.py` exists.**                                                                                                                                                     | **Confirms a real, pre-existing daemon gap**, independent of `planlib`: `# shellcheck disable=` comments in **any** shell script anywhere in a project are currently unchecked by the daemon. `planlib`'s R9 would close this only for plan-folder scripts specifically; the general gap (all `.sh`/`.bash` files) is a separate, smaller, standalone fix the daemon could make regardless of this proposal's fate.                                                                                                                                                                                                                       |
| `scripts/qa/run_shell_check.sh` (existing shell QA gate, part of `run_all.sh`)                                                                                                          | Runs `shellcheck -x -f json` over every `.sh`/`.bash` under `scripts/` and `src/`; passes iff zero **error**/**warning**-level issues (info/style tolerated).                                                                                                                        | Not overlap, but relevant to feasibility: `_planlib.inc.bash` already passes this gate today — it was independently confirmed clean at `-S style`, which is *stricter* than what this existing gate requires. Dropping the file into `src/` (or wherever it lands) would not need shell-QA remediation work to clear the daemon's own bar.                                                                                                                                                                                                                                                                                                |
| `PlanWorkflowQaConfig.extra_root_files` docstring (`config/models.py`, added in commit `b1a586ca`, **Plan 00153, 2026-07-12** — predates this proposal)                                 | Docstring: *"Use for a legitimately-placed shared file such as a sourced `_planlib.bash` shell library."*                                                                                                                                                                            | Not overlap, but a striking corroborating data point: the daemon's own config schema was **already anticipating a file named `_planlib.bash`** as the canonical example of a legitimate plan-root exception, over three weeks before this proposal's timestamp. Circumstantial (a plausible name could be a coincidence), but it suggests this class of tooling was already on the daemon maintainers' radar, not a left-field foreign concept.                                                                                                                                                                                           |

### 2.1 The honest answer, stated plainly

The task brief asked me to say so if "most of this already exists here." It
does **not**. The overlap is minimal and mostly additive (error-hiding
patterns already partly covered; the deploy-asset seam already exists and is
reusable). `mkplan.bash`, `deploy-plan-workflow`, and the entire `plan_qa`
catalogue operate at a different lifecycle stage (plan **creation** and
`PLAN.md` **hygiene**) from what `planlib` addresses (safe **execution** of
operator-run scripts that happen to be filed inside a plan folder). This is a
genuine capability gap, not a reinvention.

### 2.2 The architectural question that overlap analysis alone doesn't answer

`planlib` is explicitly **operator-invoked by design** (§9: "the
authoring/running split ... is a policy, not a capability boundary" — a human
runs `deploy.bash` from their own terminal). It has **no runtime relationship**
to Claude Code hook events, the daemon socket, or any handler dispatch. Its
only connection to "plans" is filing convention — `PLANLIB_PLAN_DIR` is used
for message text and default log placement only; "the library never
enumerates it" (§3.1's own comment). A project could use `planlib` with no
hooks daemon installed at all, and could use the hooks daemon with no
`planlib` script ever written.

Compare that to `mkplan.bash`, which is tightly coupled to daemon-owned state
(the git-anchored plan counter that `plan_qa`'s checks also read, the
`PLAN.md` template shape the edit-time linter enforces). `mkplan.bash` belongs
here because the daemon **owns** the thing it manipulates. `planlib` would be
the first daemon-distributed artefact with **zero** runtime coupling to
anything the daemon governs — it rides along only because the installer is a
convenient distribution channel. That's a legitimate thing to want (precedent:
`mkplan.bash`, journal templates), but it's also exactly the kind of
scope-fit judgement call the plan's own Non-Goals section reserves for a
human, not something the overlap table resolves by itself. I'm surfacing it
rather than deciding it.

---

## 3. Recommendation detail

**ADAPT**, not full accept, not decline:

- **Decline would be wrong.** The core artefact is genuinely solid, verified
  exactly as claimed by both the static checks the proposal names and my own
  additional dynamic smoke tests, and it solves a real incident class
  (§1.1's `git rev-parse --show-toplevel` cwd bug) with primitives that would
  be tedious and easy to get subtly wrong if reinvented independently (the
  named-pipe-not-`>()`-substitution reasoning in §3.6, the `BASH_SUBSHELL`
  leg guard, the TTY-vs-stdin prompt-ordering traps in §3.8 are all the kind
  of thing that looks obviously right until it silently isn't).

- **Full accept would overclaim what's ready.** Of the three artefacts named
  in the proposal's own table, only the library (#1) is delivered as
  complete, runnable, independently-verified code. The QA handler (#2) and
  test suite (#3) are design sketches — a rules table, a couple of
  illustrative snippets, four testing principles. Folding "write a rule
  engine and a test harness from a bullet list" into this plan's Phase 2 as
  currently scoped (four short tasks) understates the work by a wide margin,
  and this project's TDD discipline has no RED phase to start from for those
  two pieces.

- If a human decides to proceed, I'd suggest re-scoping Phase 2 into two
  plans rather than one: land artefact 1 alone behind config
  (`plan_workflow.scripts.*`, defaulted inert — no default `root_marker`,
  matching §3.1's own "no wrong default" reasoning) via the existing
  `deploy_plan_workflow_if_enabled` seam, exactly as this plan's Goals
  section already says; then a **separate**, honestly-scoped follow-up plan
  to design and TDD `plan_script_qa` and `test-planlib.bash` from scratch,
  informed by (but not copying wholesale) the rules table and principles in
  §6/§7.

- The one open question I cannot resolve from inside the repository is
  whether a general-purpose, plan-system-agnostic bash safety library
  belongs in a **Claude Code hooks daemon** at all, versus being a separate
  vendored shared library the daemon merely helps distribute. That's a scope
  call, and per this project's own conventions around scope decisions, it's
  the human's to make — not something "the code is good" settles.
