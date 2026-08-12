# Assessment of the `planlib` proposal

Supporting analysis for Plan 00199. **Source document:
`untracked/hooks-daemon-plan-lib-v2.md` (1,327 lines)**, which supersedes the
earlier `hooks-daemon-plan-lib.md` (1,226 lines). All section references below
are to **v2**; v1's numbering differs from §3.5 onward (see §11).

This file records the integration points, the rule triage, the
identifier-hygiene review, and the critical objections — so `PLAN.md` can stay
a lean spec.

## 1. The daemon already anticipated this

The strongest evidence that this proposal is not speculative is that **the
codebase already names the file it proposes**, in two independent places:

- `config/models.py:544` — the `extra_root_files` config option's docstring:
  "Use for a legitimately-placed shared file such as a sourced
  `_planlib.bash` shell library."
- `plan_qa/model.py:431` — the same example, on the plan-tree scanner.

Someone previously added a config escape hatch **specifically so a project
could place this library at the plan root without the sweep flagging it as a
stray file**. That tells us three things:

1. The library belongs at the plan root (`CLAUDE/Plan/_planlib.inc.bash`),
   alongside `mkplan.bash`.
2. The need is already recognised; today each project must opt in by hand via
   `extra_root_files`.
3. If the daemon *ships* the library, it should join the built-in accepted set
   `_EXPECTED_ROOT_FILES` (`plan_qa/model.py:306-314`, currently
   `{README.md, CLAUDE.md, mkplan.bash, _TEMPLATE_.md, _JOURNAL_TEMPLATE_.md}`)
   rather than making every project configure it.

**Naming discrepancy to resolve**: the codebase says `_planlib.bash`; the
proposal says `_planlib.inc.bash`. See PLAN.md Decision 3.

## 2. The deployment vehicle already exists

`install/plan_workflow.py` is a working precedent for shipping a bash asset
into a client's plan directory, with an explicit ownership contract:

- **daemon-owned, overwritten every upgrade**: `_deploy_mkplan`
  (`install/plan_workflow.py:277-292`) writes the template and `chmod 0755`s
  it, deliberately overwriting "so audit fixes reach existing installs"
- **client-owned, never overwritten**: `_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md`,
  `PlanJournalling.md` (`install/plan_workflow.py:232-274`, `:295-345`)
- single gated decision site: `deploy_plan_workflow_if_enabled`
  (`install/plan_workflow.py:348-387`), wired into install and both upgrade
  paths, plus the `deploy-plan-workflow` CLI (`daemon/cli.py:3325`)

`_planlib.inc.bash` is unambiguously **daemon-owned**: it is the library whose
whole purpose is that the correct behaviour is the only behaviour on offer
(proposal §1.2). A client-owned copy would re-introduce the divergence the
proposal exists to eliminate.

One difference from `mkplan.bash`: the library is **sourced, not executed**, so
it must NOT get the execute bit. `_MKPLAN_MODE = 0o755`
(`install/plan_workflow.py:24`) must not be reused; `0644` is correct.

## 3. Where the QA rules should live — the main architectural question

The proposal (§6.1) specifies a **new, separate** rule engine:

```
_plan_script_rules.py   the whole rule engine ... Imports NOTHING from the daemon.
plan_script_qa.py       a thin Handler wrapper around it.
```

with the rationale that the daemon "typically lives in a git-ignored directory
and is therefore absent from a CI checkout", so anything importing it cannot be
gated by CI.

**That architecture already exists in this repo, as `plan_qa/`.** Verified
directly:

- `plan_qa/` is 42 modules / ~4,406 LOC / 30 checks and imports exactly **two**
  symbols from the rest of the daemon, both in one file
  (`plan_qa/gitfacts.py:23-24`) — a timeout constant and a git-config counter
  reader. Everything else is stdlib.
- It has no pydantic dependency: config is bound by structural `Protocol`s
  (`plan_qa/context.py:29-107`) that the pydantic models satisfy without either
  side importing the other.
- It ships its own policy defaults (`plan_qa/types.py:38-59`) so it runs with
  no config source at all — the docstring at `types.py:43` says this is to keep
  the package "usable standalone".
- It already has the three surfaces the proposal wants (EDIT / COMMIT / SWEEP —
  `plan_qa/types.py:23-28`), a `Finding` type with block/advise levels
  (`types.py:82-90`), grandfathering allowlists (`types.py:112-113`), and a
  CI-able CLI that exits 1 on findings (`daemon/cli.py:3357-3452`).

So the proposal's CI constraint is **already satisfied** by the existing
engine. Building `_plan_script_rules.py` beside it would create a second check
catalogue, a second `Finding` shape, a second report renderer, a second config
block and a second CLI — for rules that are conceptually "plan QA". That is a
direct DRY violation against this repo's stated principles.

**Recommendation**: implement the script rules as additional `CheckSpec`s in
the existing catalogue (`plan_qa/checks/`), reusing `Stage`, `Finding`,
`Level`, the allowlist machinery and the report renderers. See PLAN.md
Decision 1 for the trade-offs and the one place this fit is imperfect.

## 4. Rule triage — the 16 rules are not equally shippable

The proposal lists 16 rules (§6.3 — R1..R15 plus **R7b, new in v2**). They
differ enormously in how mechanically checkable they are, and shipping them as
one block is what would make the gate noisy enough to be switched off (the
proposal's own §8 warns about exactly this).

| Rule | Forbidden shape                                                     | Checkability                           | Ship in      |
| ---- | ------------------------------------------------------------------- | -------------------------------------- | ------------ |
| R1   | `git rev-parse --show-toplevel`, absolute path, fixed-depth `../..` | Crisp regex                            | First        |
| R3   | raw `exec > >(tee …)`                                               | Crisp regex                            | First        |
| R5   | `$(… \| tee /dev/stdout)`                                           | Crisp regex                            | First        |
| R7b  | `plan_deploy_leg` inside `$( )`, `( )` or a pipeline stage          | Crisp regex, **supplied in §6.3**      | First        |
| R9   | `2>/dev/null`, `\|\| true`, `# shellcheck disable=`                 | Crisp regex                            | First        |
| R12  | file mode not executable                                            | Filesystem stat                        | First        |
| R2   | bare `ssh-add`; keys after `plan_start_log`                         | Regex + line ordering                  | First        |
| R4   | bare `read` after the log                                           | Regex + line ordering                  | Second       |
| R7   | leg runner not matching declared mode                               | Regex pair                             | Second       |
| R8   | gather that gates; deploy that does not                             | Regex pair                             | Second       |
| R6   | hand-rolled runner argv with credentials                            | Heuristic                              | Second       |
| R10  | header, `WHERE TO RUN`, `-h`, idempotence statement                 | Structural, partly subjective          | Second       |
| R11  | raw `ssh user@host`, per-host loops                                 | Heuristic, project-specific            | Third        |
| R13  | operator shell redirect `> report.txt`                              | Heuristic                              | Third        |
| R15  | a `deploy` carrying its own definitions                             | Needs `PROJECT_SOURCE_PREFIXES` config | Third        |
| R14  | adversarial review before an operator runs it                       | **Not mechanically checkable at all**  | Never — docs |

**R7b is the best-specified rule in the set** and lands in the first tier
despite being newest: v2 ships its regex (`_RE_LEG_IN_SUBSHELL`) inline. Its
rationale is the important part — the runtime `BASH_SUBSHELL` guard fires only
when that line *executes*, so a `plan_deploy_leg` buried in a rarely-taken
branch ships undetected. This was listed as a known limit in v1 and has been
closed by a static rule in v2.

**R14 must not be a gate rule.** It is a process obligation about human
review. Encoding it as a check means either a rule that never fires or one
that fires on everything. It belongs in the deployed guidance doc.

**R15 needs project configuration** (`PROJECT_SOURCE_PREFIXES` in the
proposal's §6.4 sample) that has no daemon-side equivalent yet, and its own
sample admits the predicate must treat any variable expansion as core to avoid
crying wolf. It is the least ready of the sixteen.

## 5. Identifier hygiene — reviewed

The team lead asked me to watch for identifiers carried over from the private
infrastructure repo. **The document is already well scrubbed**, and v2
strengthens the provenance statement (every project-specific fact pulled into
the §2 configuration seam). No employer, client, hostname or person name
appears. The one concrete path in the incident report (§1.1) is already
anonymised to `/home/user/Projects/other-repo/files/var/local/tool/tool`.

What *does* remain is **domain flavour from the originating stack**, which
must not be copied into daemon defaults or docs:

| Location         | Residue                                                    | Handling                                                                   |
| ---------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| §8 config sample | `root_marker: "ansible.cfg"`                               | Use a neutral example; there must be **no** default (§3.1)                 |
| §8 config sample | `delegate: "shellscripts/ansible-run.bash"`                | `shellscripts/` is the originating repo's layout — genericise              |
| §8 config sample | `force_color_var: "ANSIBLE_FORCE_COLOR"`                   | Keep the mechanism, change the example                                     |
| §8 config sample | `scrubber: "shellscripts/scrub-secrets.py"`                | Genericise the path                                                        |
| §3.10 prose      | vault-id, bastion `ProxyCommand`, encrypted connection key | Illustrative only — do not encode in the library                           |
| §6.3 R11         | "hypervisor guest-exec"                                    | Ansible/infra-specific; belongs in per-project config, not a built-in rule |

None of this is a leak; it is scope contamination. The library core is
genuinely stack-neutral — the seam at §2 is the correct boundary and holds up.

## 6. Technical content worth preserving verbatim

These are the parts where the proposal's reasoning is load-bearing and a
re-implementation from memory would get it wrong. They should be carried into
the library with their comments intact:

- **Root resolution** (§3.3): marker tested *before* boundary; `-e` so a
  worktree's `.git` **file** bounds the walk; no `git` subprocess; the marker
  must not be `.git` or the boundary check can never fire.
- **Run log** (§3.6): `mkfifo` + waitable background reader rather than
  `>(…)`, because a process substitution cannot be waited on and the final
  buffered chunk — the lines written as the run died — is lost. One PID for
  the whole `{ tee | awk ; } 3>&1 &` group. Traps on INT/TERM/HUP as well as
  EXIT.
- **Drain ordering** (§3.6): `wait` **then** scrub. Scrubbing first lets the
  writer append past the scrubber into a log that reports itself clean.
- **Quarantine** (§3.7): rename to `.unscrubbed` rather than delete or fail,
  so the only losable thing is the log's presence in git, never an uncleaned
  log's presence in a commit.
- **Prompt plumbing** (§3.8): prompt text to stdout (ordered through the tee),
  reply from `/dev/tty`, mandatory trailing newline, and `true >/dev/tty` as
  the openability probe rather than `[ -e /dev/tty ]`.
- **ssh-agent exit-code triage** (§3.5, expanded in v2): `ssh-add -l` returns
  0 / 1 / 2 / 127 for "listing" / "agent up but empty" / "no agent reachable" /
  "ssh-add missing". Every failure is *reported*; the listing is empty when
  unknown, so the caller falls through to a load attempt rather than wrongly
  skipping a key. `plan_load_ssh_keys` degrades to a recorded warning in
  gather mode and stays fatal in deploy mode.
- **`BASH_SUBSHELL` guard** (§3.11): a `plan_deploy_leg` inside `$( )`, a
  pipeline or `( )` would `exit` only the subshell, so the run looks aborted
  and continues. `kill -TERM "$$"` takes the real process down.
- **`|| return 1` convention** (§3.2): under `set -e` a bare `_plan_err` ends
  the caller before the following `return`, skipping cleanup.
- **Two `source-path` directives** (§4): a plan folder moves into `Completed/`
  on archive, changing the depth to the library; without both directives
  `shellcheck -x` emits SC1091 and archiving a plan turns CI red on a commit
  that looks unrelated to shell code.

## 7. The objections

Recorded here in full; PLAN.md carries the summary.

### 7.1 The daemon would not dogfood it

This is the strongest objection. Every other asset the daemon deploys is used
constantly by the daemon's own maintainers — `mkplan.bash` runs on every plan,
the plan QA checks fire on every edit. **`_planlib.inc.bash` would not be.**
This is a Python project; its plans ship Python and tests, not `deploy.bash`
orchestrators against live infrastructure.

The repo's dogfooding rule (CLAUDE.md, "Dogfooding Bug Fixes") exists precisely
because unused code rots invisibly. A safety-critical bash library whose
maintainers never run it in anger is a liability — and the failure mode it
guards against (a control that reports success without doing its job) is
exactly the failure mode an untested deployment path would have.

**Mitigation, and its limit**: the proposal's artefact 3 (`test-planlib.bash`)
is explicitly the thing that makes the library safe to change (§7), and its
four principles — pure predicates, assert the mechanism not the exit code,
negative controls by perturbation, state what is uncovered — are strong. A
comprehensive suite substitutes for dogfooding *for the logic*. It cannot
substitute for it on the deployment path (does the file arrive, with the right
mode, at the right path, on install and on upgrade), which is why that path
needs its own test against the client-mode fixture
(`scripts/dummy-client-repo.sh`).

### 7.2 Artefact 2 has nothing to gate

`plan_script_qa` enforces that orchestrators are built on the library. In this
repo there are **zero** orchestrators. Shipping the handler here means shipping
a gate whose entire enforcement surface is empty, whose `legacy_script_allowlist`
has no baseline to seed, and whose ratchet (§11 step 3) has nothing to ratchet.

Its rules would be validated only by unit tests written from the same document
that specified them — no independent signal. That is a real risk of shipping
16 rules that are individually plausible and collectively wrong about how real
orchestrators look.

### 7.3 Sixteen rules is a large surface for an unproven feature

The proposal's own §8 argues the gate must ship `warn` because "a gate that
starts red against every existing file is one everybody learns to skip". The
same logic applies to rule count: a gate with sixteen rules, several heuristic,
is one that produces enough noise to be disabled before it earns trust.

### 7.4 Where the objections land

They kill **artefact 2's timing**, not the proposal. Artefacts 1 and 3 stand on
their own: the daemon is the correct distribution point (it already ships
`mkplan.bash` by exactly this mechanism), the config already anticipates the
file, and the library's value does not depend on anything enforcing its use.

Artefact 2 should wait for a real consumer — at least one project with
orchestrators actually built on the library — so its rules can be validated
against code that was not written from its own specification.

## 8. Two verification techniques v2 supplies, which the plan adopts

Both are non-obvious, both defend against "a check that passes without
checking" — the proposal's own thesis turned on its tooling.

**`bash -n` cannot be trusted on exit code alone.** For a malformed conditional
it prints a diagnostic to stderr and **still exits 0**. The actual signal is
*silence on stderr*. A syntax gate that only checks `$?` is exactly the class
of control this proposal exists to eliminate, so the plan's syntax check must
assert stderr is empty (PLAN.md Task 2.10).

**A red suite is not the same as the right assertion firing.** v2 §7 records
that the author's first attempt at perturbation testing injected
`set -euo pipefail` into the library, which aborted the harness on its first
assertion — rc=1 with **zero assertions reported**. The probe looked like it
worked and proved nothing. The consequence for Task 1.1/1.8: the harness must
report an assertion *count*, and a negative control must assert that exactly
the expected assertion failed — not merely that the suite went red.

v2 also records two worked perturbations to reproduce: removing the `HUP` line
from `plan_start_log`'s trap block must produce exactly one failure naming HUP;
injecting `set -o pipefail` must produce exactly one failure naming the
shell-options rule.

## 9. What v2 changed, and why it matters here

v2 is not a light edit. The material deltas:

| Change                                                                                                                         | Consequence for this plan                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **§3 is now complete and self-contained** — the blocks concatenate into a working library; v1 was excerpted, with `...` bodies | Phase 2 becomes *transcribe and verify*, not *reconstruct*. Materially lowers the risk called out in "Why this might not be worth doing" |
| Functions v1 only referenced are now defined: `_plan_agent_listing`, `plan_load_ssh_keys` (full), `plan_list_reports`          | Task 2.9 no longer has to invent them                                                                                                    |
| **R7b added** (`plan_deploy_leg` must be top-level), with its regex                                                            | Rule count 15 → 16; new rule joins the first ship tier (§4)                                                                              |
| `PLANLIB_CHECK_FLAG` and `PLANLIB_FORCE_COLOR_VAR` promoted to first-class seam members (§2, §3.1)                             | Task 3.5 config model must carry both                                                                                                    |
| Author's own verification table (`bash -n` + stderr, `shellcheck -x -S style`, call-graph cross-reference)                     | Adopted as Task 2.10; see §8                                                                                                             |
| Perturbation worked examples and the "red suite" trap (§7)                                                                     | Adopted as Task 1.8; see §8                                                                                                              |
| `plan_load_ssh_keys` scoped: it is for the **operator's own** key, not for reaching infrastructure — the delegate owns that    | Prevents a plausible misreading during implementation                                                                                    |
| New known limit: `plan_list_reports` matches `*report*` by filename                                                            | Accept as-is; the alternative is a manifest                                                                                              |
| Sections renumbered from §3.5 onward                                                                                           | All citations in this plan now use v2 numbering                                                                                          |

**Nothing in v2 changes any of the four Technical Decisions.** §6.1 still
proposes a separate rule engine (Decision 1 still dissents); the adoption order
still ships library and suite together (Decision 2 stands); filename, mode and
ownership are untouched (Decision 3); and v2 adds no orchestrators to this repo,
so the deferral rationale is unchanged (Decision 4). v2 makes the *work*
cheaper and better specified without moving any decision.
