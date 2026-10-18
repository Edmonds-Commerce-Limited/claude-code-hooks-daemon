# Plan 00532: rulings on QUESTIONS.md Q1 to Q9

**These are FABLE rulings, not owner rulings.** They were made by a Fable
sub-agent under the project owner's standing delegation for an unattended
session: design questions are answered by a Fable sub-agent and recorded as
such. The owner has not seen them. Where a ruling touches product direction
rather than engineering evidence, the section says so and the conservative
option was taken; the owner can overturn any of them by editing this file and
re-cutting PLAN.md.

Constraints applied to every ruling: the daemon never edits a client's own
files without explicit confirmation (report or propose before apply); no QA
suppressions, allowlist or exclusion entries; nothing published outside the
repository; the first version is small enough to ship and verify, with the
rest deferred into named follow-up tasks.

Evidence read: `PLAN.md`, `QUESTIONS.md`, `CLAUDE/core/DocumentationStrategy.core.md`
(R6, R7a, R7b, R7d, the checks table), `src/claude_code_hooks_daemon/docs_qa/checks/rules_file_shape.py`,
`src/claude_code_hooks_daemon/skills/docs-qa/SKILL.md`, `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md`,
`src/claude_code_hooks_daemon/install/skills.py`,
`src/claude_code_hooks_daemon/handlers/session_start/contract_staleness.py`,
`contracts/claude-code-hooks/META.json`, `CLAUDE/development/claude-code-versions.yaml`,
`remote-docs/code.claude.com/docs/en/memory.md`, `CLAUDE/LLM-INSTALL.md`
(install is a `git clone` into `.claude/hooks-daemon/`), and the issue #123
text as a hypothesis.

Two facts the rulings lean on that QUESTIONS.md left open:

- A client install is a git clone of the daemon repository, so `contracts/`
  and `remote-docs/` are on disk at every client, and `contract_staleness`
  already has a client-side advisory branch (`_client_context`). The
  "remote-docs is not shipped to clients" doubt under Q3 option C is
  therefore not a reason to reject C; C is rejected on other grounds.
- Skills are deployed unconditionally by `deploy_skills` (every directory
  under the bundled skills root); only agents carry an `enabled` key. A
  config-gated skill would be a new mechanism, not a reuse.

## Q1: Delivery surface

**Ruling: C**, as a variant: the measurement is `hooks-daemon docs-qa --footprint [--json]`
(a flag of the existing `docs-qa` CLI verb, not a new top-level verb), and
the judgement lives in a new skill named `docs-optimise`.

The split between tested measurement and model judgement is the pattern Plan
00284 already proved with `docs-qa --sweep --json` plus the agent, and a
footprint number the model re-derives on each run (option A) cannot be
tested against the contract. Option D is rejected because `docs-qa` states a
read-only contract in both its skill and its agent definition, and a skill
that produces a proposal (Q2) is a different promise to the user.

Trade-off accepted: one more top-level slash command in every client, and
two skills (`docs-qa`, `docs-optimise`) whose names a user must tell apart.
The `docs-optimise` SKILL.md names `docs-qa` as its verification step (Q8)
so the relationship is stated where the user reads it.

## Q2: How far it goes on a client's files

**Ruling: B only in the first version.** The skill writes the proposed new
files and a unified patch under the project's scratch location
(`untracked/scratch/docs-optimise/<run-id>/`), never touches a tracked file,
and tells the user how to apply the patch. **C is deferred** into a named
follow-up ("Task F1: confirmed apply path") that is not part of this plan's
success criteria.

The standing constraint is that the daemon never edits a client's own files
without explicit confirmation, and the first version must be small enough to
verify; a proposal in scratch satisfies the issue's complaint (nothing today
"proposes the split") without any write-side guard to get wrong. C's guard
set is recorded now so the follow-up does not re-derive it: refuse on a
dirty tree, one commit per move, never touch the daemon-injected
`<hooksdaemon>` block or a daemon-deployed artefact, create the home before
thinning the source (R7a's transition rule), and apply only a proposal the
user has seen in the same session and explicitly asked to apply. D is
rejected for the reason the planner gave.

Trade-off accepted: the human applies the patch by hand in v1, which is the
same stance `/doctor prompt-audit` takes. This is also the one ruling that
is partly a product call (whether a daemon skill should ever write a
client's instruction files); the conservative interim is to propose only,
and the owner should confirm C before the follow-up ships.

## Q3: What "kept in step with Claude Code" means concretely

**Ruling: A**, with D deferred as a named follow-up ("Task F2:
`InstructionsLoaded` verification"). The contract lives at
`contracts/claude-code-instructions/`, mirroring the hooks contract: a
`META.json` with `docs_url`, `fetch_date`, `docs_bytes`, `docs_sha256`,
`last_audited_claude_code_version` and `refresh_procedure`, plus one
machine-readable facts file in which every fact carries an id, the pinned
statement, the anchor in the vendored `memory.md` (heading slug and a quoted
phrase), and the minimum Claude Code version where the page states one.

A is the established pattern (Plans 00271 and 00486) and is the only option
the Q5 trigger can compare against and a test can load. B cannot be hashed
or tested and the core document is already 820 lines. C is rejected not
because `remote-docs/` is absent at clients (it is present) but because the
model would re-derive the rules on each run, which is neither deterministic
nor testable. D describes what did load, not what would load after a move.

Trade-off accepted: a second artefact to refresh at each audit. Mitigation:
the refresh is a section added to the existing hooks-contract refresh guide
and the release Step 1c review covers both contracts in one pass (Q5), so
there is one procedure, not two.

## Q4: Which facts the contract pins

**Ruling: B (G1 to G5)**, with one addition: the contract carries an explicit
`unmodelled` list naming the G6 inputs the measurement ignores
(`claudeMdExcludes`, `AGENTS.md` selection and the Project instructions
setting, `--add-dir` with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`,
subagent `omitClaudeMd`), and the footprint report prints that list so a
user in a monorepo knows the count may be high.

G5 changes where a must-not-forget instruction belongs (only the
project-root `CLAUDE.md` is re-injected after `/compact`), so a restructure
proposal that ignores it can move a safety instruction somewhere it
vanishes. G6 is the fastest-moving section of the page (three version-gated
`AGENTS.md` notes already) and matters to few clients; pinning it now buys
refresh cost before anyone asks.

Trade-off accepted: a project using `claudeMdExcludes` or `AGENTS.md` gets
an overcount or a miscount in v1, declared in the report rather than
modelled. G6 is "Task F3: variants group" in the follow-ups.

## Q5: How re-audit is triggered

**Ruling: D and E.** `contract_staleness` is extended to read a second
`META.json` and emit one advisory per version in the daemon repository when
the installed Claude Code is newer than the instructions contract's audited
version; release Step 1c's changelog review brief gains an
instruction-loading item that names the contract; the vendored page's hash
in `META.json` is the evidence the refresh records (B). The existing
integration test that ties the hooks `META.json` version to
`claude-code-versions.yaml` is extended to the second `META.json`, so both
audits must move together at release time.

Client-side, no new SessionStart advisory: the `docs-optimise` report prints
the contract's audited version next to the installed Claude Code version, so
the mismatch is visible at the moment it matters, and the user's only action
(upgrade the daemon) is the one `contract_staleness` already tells clients
about for the hooks contract. F is cheap to add later because the client
branch exists, and is "Task F4: client-side staleness advisory" if a client
asks.

Trade-off accepted: a client whose docs guidance has gone stale learns it
only when they run the skill, not at session start.

## Q6: Whose ruleset governs the restructure

**Ruling: C.** When `documentation.enabled` is true in the client's
`.claude/hooks-daemon.yaml`, the daemon ruleset governs: a rules file is a
pointer target only (R7a), the substance goes to the agent tree or a
registered module `CLAUDE.md` (R7d), and no proposal adds an `@`-import
outside the resident set (R6). Otherwise Claude Code's own guidance governs
and a `paths:`-scoped rules file may carry substantive instructions. The
report's first lines state which ruleset applied and why.

A client that opted into the ruleset must not be handed a proposal its own
`rules_file_shape` check then flags; a client that did not opt in should not
have the house style imposed through a restructure tool. In neither mode
does a proposal add a `resident_at_imports` or `grandfather_allowlist`
entry, per the standing constraint on allowlists.

Trade-off accepted: two classification paths to test. Mitigation: the two
differ only in the target for a path-scoped section (rules file versus
agent-tree document plus pointer), so the fixture set is one client corpus
run under both modes.

## Q7: Client opt-in and default

**Ruling: A**, which follows from Q2 ruling B: a proposal-only skill costs a
client nothing but a slash command, and `deploy_skills` already deploys every
bundled skill with no per-skill gate, so A is also the option with no new
mechanism. The apply opt-in key belongs to the Q2 follow-up (Task F1) and is
named there, not here.

Trade-off accepted: one more slash command in every client, with no way to
hide it short of deleting the directory (which the next upgrade re-creates).
If that proves unwelcome, a per-skill `enabled` key is a small change and is
noted under Task F1.

## Q8: Relationship to docs-qa and to `/doctor`

**Ruling: D.** The skill owns placement and footprint only. Its report ends
with two named next steps: `/docs-qa` (scoped to the touched files) to
re-verify SSoT after a proposal is applied, and `/doctor prompt-audit` for
outdated, missing-reference and contradictory content, which the skill does
not re-implement. The `docs-qa` agent's read-only contract is unchanged.

Building a second prompt audit would duplicate a built-in whose behaviour the
daemon does not control and would drift from it; naming it as a pointer in a
report is a dependence the daemon can live with because a missing `/doctor`
(older Claude Code, bundled skill disabled) degrades to a sentence the user
ignores, not a failure.

Trade-off accepted: two skills to learn, and a report that ends with
instructions rather than finished work.

## Q9: Scope of files the skill may propose moving

**Ruling: A.** The proposable set is root and nested `CLAUDE.md`,
`.claude/CLAUDE.md`, `.claude/rules/**` (recursive, per the contract), and
files those import inside the repository. `CLAUDE.local.md` and user-scope
files (`~/.claude/CLAUDE.md`, `~/.claude/rules/`) are counted in the
footprint because they load, and are never proposed for edits. The
daemon-injected `<hooksdaemon>` block and daemon-deployed artefacts are
counted and never proposed (PLAN.md Task 3.2).

A move out of a gitignored or home-directory file cannot be reviewed in a
pull request or reverted with git, and the daemon's own containment guard
denies writes outside the repository, so a proposal there could not be
applied by the follow-up either.

Trade-off accepted: a user whose always-loaded weight is in
`CLAUDE.local.md` or user scope gets the numbers and a sentence saying the
skill will not propose there, and nothing more.

## Named follow-ups (not in this plan's success criteria)

- **Task F1: confirmed apply path** (Q2 C, Q7 opt-in key): owner
  confirmation required before it ships.
- **Task F2: `InstructionsLoaded` verification** (Q3 D): compare observed
  loads with the contract's prediction.
- **Task F3: variants group** (Q4 G6): `claudeMdExcludes`, `AGENTS.md`,
  `--add-dir`, `omitClaudeMd`.
- **Task F4: client-side staleness advisory** (Q5 F): extend
  `contract_staleness`'s client branch to the instructions contract.
