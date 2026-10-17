# Plan 00532: open decisions

Each question depends on product intent and is for the ruling agent. Every
option lists its trade-offs; the recommendation is the planner's, with
reasons, and is not a ruling. Record the ruling under each question.

Facts the options rely on (all from
`remote-docs/code.claude.com/docs/en/memory.md` unless stated):

- At launch Claude Code loads `CLAUDE.md` and `CLAUDE.local.md` from the
  working directory and every ancestor, `./.claude/CLAUDE.md`, and rules
  without `paths` frontmatter. Nested `CLAUDE.md` files load when Claude
  reads, writes or edits a file in that subdirectory. A `paths:`-scoped rule
  loads when Claude uses Read, Write or Edit on a matching file.
- `@path` imports are expanded at launch, recursively, to a maximum depth of
  four hops. Imports inside code spans and fences are not parsed. Imports
  "help you organize a long file but don't reduce its context cost".
- Rules are discovered recursively under `.claude/rules/`. `paths` is the
  only frontmatter field Claude Code reads from a rule; other fields are
  ignored. Unparseable frontmatter makes the rule load as if unscoped.
- Size guidance: target under 200 lines per `CLAUDE.md`; a startup warning
  fires for a file over the recommended length and for files that add up past
  a combined limit; a file over 4 MiB is skipped.
- Only the project-root `CLAUDE.md` is re-injected after `/compact`; nested
  files and scoped rules reload on demand.
- `AGENTS.md` is read in place of `CLAUDE.md` only when no `CLAUDE.md` exists
  on the path (v2.1.277+), configurable via the Project instructions setting.
- Explore and Plan subagents start without `CLAUDE.md`; a custom subagent can
  set `omitClaudeMd` (`sub-agents.md`).
- Claude Code ships `/doctor prompt-audit` (v2.1.283+), which reports
  outdated or conflicting instructions with proposed edits and changes nothing
  until asked, and a `/doctor` checkup that proposes trims for a checked-in
  `CLAUDE.md`.
- The `InstructionsLoaded` hook event reports each instruction file loaded,
  with `memory_type` and `load_reason`
  (`contracts/claude-code-hooks/InstructionsLoaded.json`); the daemon has no
  handler for it today.

## Q1: Delivery surface

What does the client invoke?

- **A. Skill only.** A new skill (agent-driven judgement) with no new CLI
  verb. Cheapest; but the footprint measurement is then re-derived by the
  model on every run, which is neither deterministic nor testable.
- **B. CLI verb only** (for example `hooks-daemon docs-qa --footprint`).
  Deterministic and testable; but a CLI cannot make the judgement call of
  which section belongs where, which is the heart of the ask.
- **C. Both: a deterministic CLI measurement plus a skill that consumes its
  JSON and does the judgement.** Mirrors how the `docs-qa` skill already
  pairs `docs-qa --sweep --json` with an agent.
- **D. A new subcommand of an existing skill** (`/docs-qa restructure` or
  `/hooks-daemon docs-optimise`) backed by the CLI in C. One fewer top-level
  slash command; but `docs-qa` is today a pure read-only audit shim, and
  folding a writing workflow into it changes its contract.

**Recommendation: C**, with the measurement as a flag or subcommand of the
existing `docs-qa` CLI rather than a new top-level verb. The split between
measurement (code, tested) and judgement (skill) is the pattern Plan 00284
already proved, and a separate skill keeps `docs-qa`'s read-only contract
intact (see Q2 and Q8).

**Ruling:**

## Q2: How far it goes on a client's files

- **A. Report only.** Footprint numbers and a ranked list of candidate moves.
  Zero risk; but the issue explicitly says nothing today "proposes or
  performs the split", and a report alone is close to what `/doctor` already
  gives.
- **B. Propose a concrete diff, never apply.** Writes the proposed new files
  and edits to a scratch location (or prints a patch) for the human to apply.
  Safe and reviewable; the human does the apply step by hand.
- **C. Apply edits after explicit confirmation, in a clean working tree only,
  one commit per move.** Each move is reversible with `git revert`; the skill
  refuses on a dirty tree, never touches the daemon-injected block or
  daemon-deployed artefacts, and follows R7a's create-the-home-first order so
  no move deletes the only copy. Most useful; most risk, and it relies on the
  host's own permission prompts plus the daemon's guards.
- **D. Apply automatically.** Rejected by the planner: an unattended rewrite
  of a client's always-loaded instructions changes the agent's behaviour
  silently, which is the failure this daemon exists to prevent.

**Recommendation: B by default, C on explicit request** (the user asks the
skill to apply a proposal it has shown). This matches `/doctor prompt-audit`'s
"nothing changes until you ask" stance, so the two tools behave alike, and C's
guards (clean tree, per-move commits, protected daemon-owned spans) make the
apply path safe to offer.

**Ruling:**

## Q3: What "kept in step with Claude Code" means concretely

- **A. A versioned loading-rules contract,** like the hooks contract: a
  machine-readable file of pinned facts, each citing its anchor in the
  vendored upstream page, plus a `META.json` with the upstream doc's hash,
  fetch date and `last_audited_claude_code_version`. The skill, the core
  document and the checks cite it. Most rigorous; one more artefact to
  refresh at each audit.
- **B. A prose section** in the core document listing the loading facts and
  the version they were checked at. Cheap; but prose cannot be tested or
  hash-compared, and the core document is already long.
- **C. Point at the vendored `memory.md` directly** and let the skill read it
  at run time. Always as fresh as the vendored copy; but `remote-docs/` is
  not shipped to clients (to be confirmed in Phase 1), and the model would
  re-derive rules each run.
- **D. Empirical only:** derive loading behaviour from `InstructionsLoaded`
  events observed in the client's own sessions. Ground truth for the
  installed version; but it cannot describe what would load after a
  restructure, only what did load before.

**Recommendation: A, with D as a later verification aid.** A is the
established pattern (Plan 00271, Plan 00486) and gives the re-audit trigger in
Q5 something to compare against. D is a cheap follow-up that would let the
daemon confirm the contract against real loads, but it should not be the
source.

**Ruling:**

## Q4: Which facts the contract pins

Candidate facts, grouped. The ruling picks which groups are in scope for the
first version.

- **G1 (core load set):** which files load at launch versus on demand; ancestor
  walk; `CLAUDE.local.md`; `.claude/CLAUDE.md`.
- **G2 (imports):** `@` syntax, relative resolution, four-hop depth limit,
  code-span and fence exclusion, external-import approval, and the fact that
  imports do not reduce context cost.
- **G3 (rules):** recursive discovery, `paths` as the only frontmatter field
  read, glob semantics, the unparseable-frontmatter fallback, the load
  trigger tools (Read, Write, Edit, some Bash).
- **G4 (size):** the 200-line target, the combined-size warning, the 4 MiB
  skip, the `MEMORY.md` 200-line or 25 KB limit.
- **G5 (persistence):** what survives `/compact`.
- **G6 (variants):** `AGENTS.md` selection rules and the Project instructions
  setting, `claudeMdExcludes`, `--add-dir` with
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`, subagent `omitClaudeMd` and
  the Explore and Plan exemption.

Options:

- **A. G1 to G4.** What the footprint measurement and restructure need.
- **B. G1 to G5.** Adds compaction, which changes where a must-not-forget
  instruction belongs (root versus nested).
- **C. All of G1 to G6.** Complete; G6 is the fastest-moving area (three
  version-gated `AGENTS.md` notes in the current page alone), so it carries
  the most refresh cost.

**Recommendation: B.** G5 directly affects restructure advice (moving a
safety instruction into a nested file means it can vanish after compaction
until a file there is touched), while G6 matters to few clients and can be
added when one asks.

**Ruling:**

## Q5: How re-audit is triggered

- **A. Extend `contract_staleness`** with a second contract: when the
  installed Claude Code is newer than the loading contract's audited version,
  one advisory per version. Reuses tested code and the dedupe it already has.
- **B. Hash the vendored upstream page** on `remote-docs` refresh and flag a
  re-audit only when `memory.md` actually changed. Precise (no noise when the
  page did not change); but depends on someone refreshing the vendored copy.
- **C. Fold it into the release step** (RELEASING.md Step 1c, the Claude Code
  changelog review): the reviewer flags instruction-loading entries against
  the contract. Covered once per release; nothing between releases.
- **D. A + C**, with B as the evidence the refresh procedure records.

Second axis: where the advisory fires.

- **E. Daemon repository only** (as the changelog-review check is today: its
  record exists only there).
- **F. Client installs too:** a client whose Claude Code is newer than the
  shipped contract is told its docs guidance may be stale and to upgrade the
  daemon or re-run the skill.

**Recommendation: D and E.** The daemon repository is where the contract can
be refreshed, so that is where the signal is actionable; a client cannot
refresh it. Client-side, the skill itself should print the contract's audited
version and the installed Claude Code version in its report so a mismatch is
visible at the moment it matters, without a new SessionStart advisory.

**Ruling:**

## Q6: Whose ruleset governs the restructure

The daemon's SSoT ruleset is opinionated beyond Claude Code's own guidance:
R6 forbids `@`-imports outside a resident set, R7a requires rules files to be
pointers only (at most two imperative lines, no tables or fences), and R7d
caps unregistered nested `CLAUDE.md` files at a routing table. Claude Code's
docs, by contrast, present path-scoped rules as the main progressive-disclosure
tool for real instructions.

- **A. The daemon ruleset governs** wherever the client has the
  `documentation` subsystem enabled; proposals never produce something the
  docs_qa checks would flag.
- **B. Claude Code's guidance governs**; the daemon ruleset is advisory. A
  rules file with substantive scoped instructions is a valid target.
- **C. The daemon ruleset when `documentation.enabled: true`, Claude Code's
  guidance otherwise,** with the report stating which applied.

**Recommendation: C.** A client that opted into the SSoT ruleset must not be
handed proposals its own checks then flag; a client that did not opt in
should not have the daemon's stricter house style imposed through a
restructure tool. It also gives a clean answer to the R7a tension the
contract surfaces (Phase 1.4).

**Ruling:**

## Q7: Client opt-in and default

- **A. Ships and deploys by default**, like `hooks-daemon` and `docs-qa`
  skills today. Discoverable; one more slash command in every client.
- **B. Ships opt-in** behind a config key, as the `hooks-daemon-docs-qa`
  agent does (`agents.docs_qa.enabled: false`). Quiet by default; few
  clients find it.
- **C. Deployed by default, but its apply path (Q2 C) is opt-in** via config.
  Measurement and proposals for everyone, writes only where enabled.

**Recommendation: C** if Q2 rules B-plus-C; otherwise **A**. A read-only or
proposal-only skill costs a client nothing, while the apply path is the part
that deserves an explicit opt-in.

**Ruling:**

## Q8: Relationship to docs-qa and to `/doctor`

- **A. Separate skill that hands off to docs-qa** after a proposal or apply:
  the new skill restructures, the docs-qa agent and checks verify. Clear
  roles; two skills to learn.
- **B. Extend the docs-qa skill and agent** with a restructure mode. One
  entry point; but changes the agent's read-only contract, which the agent
  definition and the `docs-qa` skill both state.
- **C. Defer to `/doctor` for content audit** (outdated, contradictory,
  derivable content) and scope the daemon skill to what `/doctor` does not do:
  footprint against the pinned contract, progressive-disclosure placement, and
  SSoT across `CLAUDE/` and `docs/` trees. Avoids building a second prompt
  audit; ties the daemon to a built-in whose behaviour it does not control.
- **D. A plus C.**

**Recommendation: D.** The skill should not re-implement contradiction and
staleness detection that docs-qa and `/doctor prompt-audit` already cover; it
should name them as the follow-up steps and own only placement and footprint.

**Ruling:**

## Q9: Scope of files the skill may propose moving

- **A. Project scope only:** root and nested `CLAUDE.md`, `.claude/CLAUDE.md`,
  `.claude/rules/`, files they import inside the repository.
- **B. A plus `CLAUDE.local.md`.** Personal, gitignored; moves out of it
  cannot be reviewed or committed.
- **C. A plus user scope** (`~/.claude/CLAUDE.md`, `~/.claude/rules/`).
  Outside the repository; the daemon's own guards deny writes there.

**Recommendation: A**, with `CLAUDE.local.md` and user-scope files counted in
the footprint (they do load) but never proposed for edits.

**Ruling:**
