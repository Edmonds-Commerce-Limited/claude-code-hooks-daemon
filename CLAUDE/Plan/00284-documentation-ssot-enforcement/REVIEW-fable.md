# Fable Review — Documentation SSoT Strategy (Plan 00284, Task 1.1)

**Role**: read-only senior review. Evidence gathered from this repository on 2026-08-28
(three parallel read-only survey agents + direct reads of Plans 00144/00131/00132/00116
and `markdown_organization.py`). Every file:line cited below was reported against the
current working tree.

**Headline conclusion**: the proposed strategy is correct in direction and — unusually —
already *half-written inside this repo*: `docs/CLAUDE.md:3` and `.claude/skills/CLAUDE.md`
both declare "every piece of information lives in exactly one canonical file; other files
link to it". Those two 12-line routing tables have stayed accurate. Meanwhile every
hand-maintained surface that restates structured facts has drifted, in several cases into
active harm (agents instructed to run a command the daemon itself denies). The strategy
therefore does not need inventing; it needs (a) an operational pointer-vs-duplicate test,
(b) parameterisation for client repos, and (c) enforcement — because the declared policy
with no checker behind it is precisely what produced the evidence below (DBF: the missing
guard is the bug).

---

## A. Evidence audit of THIS repo

### A.1 The star finding: duplicated instructions that now contradict a live guard

The QA entry command migrated from `run_all.sh` to `llm_qa.py` for agents, and the
`enforce_llm_qa` project handler now **denies** a direct `run_all.sh` invocation. The
migration reached `CLAUDE.md:377`, `CLAUDE/development/RELEASING.md:370`, and
`CLAUDE/CodeLifecycle/{README,Bugs,Features}.md` — but NOT:

- `CLAUDE/QA.md:30,106,383,433,562,594` — still instructs agents to run `run_all.sh`
- `CLAUDE/PlanWorkflow.md:259,279` — same
- `.claude/agents/qa-runner.md:36`, `qa-fixer.md:281`, `release-agent.md:48,721` — same
- `.claude/skills/release/SKILL.md:79,127,179` — same

So today, five agent-facing files instruct a command that the daemon blocks. The
handler's own test suite records the bug
(`.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py:232`: "enforce_llm_qa
denies scripts/qa/run_all.sh while the docs instruct the agent to run it"). This is the
canonical demonstration that duplication is not a cosmetic problem: N copies means a
policy change is a graph traversal nobody performs.

### A.2 Structured-fact drift (counts, steps, tables) — every strong drift example is a structured fact, not prose

01. **QA check count**: ground truth is 24 checks (`scripts/qa/run_all.sh:333-360`).
    Stated counts found: **4** (`docs/QA-INFRASTRUCTURE.md:181-219`, which also names the
    wrong check #1), **5** (`CLAUDE/PlanWorkflow.md:264-270`), **7** (`CLAUDE/QA.md:614`
    — 560 lines below its own `:39` warning that "an earlier version claimed seven"),
    **8** (`.claude/skills/release/SKILL.md:127`). Root `CLAUDE.md:92` already states the
    correct meta-rule ("the script is the single source of truth… do not restate the
    count") — the rule exists, unenforced, and violated in four sibling files.
02. **Release pipeline step numbers**: four incompatible numberings of the same 15-step
    pipeline — `RELEASING.md` (canonical per `.claude/skills/CLAUDE.md:10`),
    `release/SKILL.md` "What It Does" (`:66-84`), the SAME skill's "Orchestration
    Details" (`:346-354`, disagreeing with its own earlier section), and
    `release-agent.md:634`. `SKILL.md` omits RELEASING.md's Step 11 (CLAUDE.md Guidance
    Audit, a BLOCKING gate) entirely — a drifted copy of a safety gate list.
03. **Handler priority bands**: three different band schemes across seven files.
    `CLAUDE.md:624-630` (56-**65** advisory), `HANDLER_DEVELOPMENT.md:465-470` /
    `docs/guides/CONFIGURATION.md:189-194` / `ARCHITECTURE.md:544-549` (56-**60**),
    `CONTRIBUTING.md:204-208` (no 100+ band), `CLAUDE/Code/HooksSystem.md:597-601` (a
    flatly incompatible 5-9/10-20/21-30/31-45/46-60 scheme), `PROJECT_HANDLERS.md:283-287`
    (a third scheme, possibly intentional for project handlers — nothing says so).
04. **Handler skeleton**: `CONTRIBUTING.md:152,169-174` — the first thing an external
    contributor reads — teaches `class MyHandler(Handler)` returning `HookResult`, the
    exact pattern `CLAUDE.md:576-581` bans and an integration test forbids; it also omits
    two mandatory abstract methods, so the taught class cannot be instantiated.
05. **venv path**: the `{slug}` component (v3.19.1) reached `CLAUDE.md:324`,
    `LLM-INSTALL.md:89`, `Worktree.md:94`, `CLIENT-MODE-TESTING.md:15` — but not
    `CLAUDE/SELF_INSTALL.md:23`, which is the one file `CLAUDE.md:347` sends readers to
    "for complete details". The fingerprint formula is spelled out verbatim in three
    files.
06. **Acceptance-test delegation**: `.claude/skills/acceptance-test/SKILL.md:16-24` says
    sub-agent execution is "unreliable and forbidden… Sub-agents cannot use Write/Edit";
    its canonical doc `CLAUDE/AcceptanceTests/GENERATING.md:334-363` says the measured
    opposite ("Sub-agents CAN use Write — TDD hooks fire normally") and prescribes
    parallel Haiku batches. A safety-relevant *empirical* finding, inverted in the copy.
07. **Plan numbering & template**: `CLAUDE/PlanWorkflow.md:107-122` still teaches 3-digit
    numbering (`001-`) against the 5-digit reality; the PLAN.md template exists in three
    places (`PlanWorkflow.md:133-140`, `docs/PLAN_SYSTEM.md:320-325`,
    `CLAUDE/Plan/.plan-template-default.md` — the only one `mkplan.bash` actually copies)
    with three different required-field sets.
08. **Bandit policy**: `PlanWorkflow.md:270` says "No HIGH severity issues"; the
    zero-tolerance policy everywhere else (`CLAUDE.md:480,519-520`, `QA.md:48`) forbids
    MEDIUM/LOW too.
09. **Stale pinned versions**: the same "install a specific version" instruction pins
    `v2.7.0` in `docs/guides/GETTING_STARTED.md:75` and `v2.5.0` in
    `CLAUDE/LLM-INSTALL.md:76` — two copies, two different stale values, ~50 versions old.
10. **Acceptance gate scope**: `CLAUDE.md:97-100` states an unconditional "ALL 15+ tests
    / minimum 30 minutes" rule that `RELEASING.md:490-494` (skip on no-handler PATCH) and
    the release skill both contradict; "15+" is stale against the current "22 passed".

### A.3 Stale pointers

- `.claude/skills/configure/SKILL.md:104` — relative link one `../` short (dead), while
  `:186-187` of the same file links the same target correctly.
- `docs/QA-RUNNER-SETUP.md:35,488` — references `.claude/agents/qa-runner-daemon.md`,
  which does not exist (real file: `qa-runner.md`).
- `CLAUDE/development/RELEASING.md:769` — `skill.md` vs actual `SKILL.md` (case).
- `docs/QA-INFRASTRUCTURE.md:14` and `docs/QA-RUNNER-SETUP.md:421` — stale vendored path
  `.claude/hooks/claude-code-hooks-daemon/` (a runnable `cd` fence that fails today).
- `docs/guides/HOOK-CONTRACT-REFRESH.md:57` — points at
  `CLAUDE/Plan/00273-.../INVENTORY.md`, which does not exist in that folder.
- `docs/PLAN_SYSTEM.md:584` — instructs saving a `CLAUDE/Plan/TEMPLATE.md` that was
  never created.
- `.claude/agents/release-agent.md:455,467,491` — links written relative to `RELEASES/`
  but living in `.claude/agents/`, dead from where they sit.

### A.4 Indexes rot fastest — and the two shapes behave predictably

- `CLAUDE/CLAUDE.md:11-70` claims to index `CLAUDE/` but lists 5 of ~20 files and none
  of six subtrees; it also mis-describes `development/QA.md` (calls it "QA pipeline";
  the file is a Black/Ruff/MyPy error cookbook) — a wrong description duplicated in
  `CLAUDE/development/CLAUDE.md:24-25`. Root `CLAUDE.md:709-723` is a fourth,
  differently-scoped index of the same tree.
- **Contrast**: `docs/CLAUDE.md` (12 lines) and `.claude/skills/CLAUDE.md` (12 lines)
  are terse SSoT routing tables — all targets verified to exist. The pattern is stark:
  *minimal pointer tables stay true; prose indexes with descriptions rot*. Descriptions
  are duplicated facts.

### A.5 Audience misplacement

- `docs/PLAN_SYSTEM.md` (1,580 lines) — agent plan-lifecycle instructions in the human
  tree, twice deferring to `@CLAUDE/PlanWorkflow.md` (`:305,:572`) while restating it
  wholesale (and drifting: findings A.2.1, A.2.7).
- `docs/QA-RUNNER-SETUP.md` (490 lines) — sub-agent harness plumbing in the human tree.
- `docs/QA-INFRASTRUCTURE.md` / `docs/CONFIG-VALIDATION.md` — carry completed-plan
  metadata headers (`**Status**: Complete / **TDD**: all tests written first`) — these
  are plan-shaped implementation records parked in `docs/` and never maintained since.
- `docs/guides/HOOK-CONTRACT-REFRESH.md:9-11` — *self-admittedly* misplaced: it lives in
  `docs/guides/` only because the markdown-location handler wouldn't let a runbook sit
  beside the artifact it describes. A location rule with no audience rule produced a
  correctly-located, wrongly-audienced file.
- Inverse: `CLAUDE/CLAUDE.md` and `CLAUDE/development/CLAUDE.md` are human-style
  folder-etiquette READMEs inside the agent tree (and are the two stalest indexes).

### A.6 Plan folders holding never-promoted durable knowledge

The plan tree holds ~130 supporting docs beyond PLAN.md; the tracked doc tree links to
two of them. Strong unpromoted examples (all verified still load-bearing):

| Plan doc                                                                           | Durable knowledge stranded there                                                                                                                                                     | Evidence it still governs the present                                                                      |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `Completed/00234-handler-value-audit/VERDICTS.md` + `RESEARCH-A..G` (~2,200 lines) | Per-handler KEEP/FIX/REMOVE verdicts for all 100 handlers; measured status-line per-render I/O cost tables; the standing rule that fire counts are inadmissible evidence for removal | Cited in shipped code (`config/models.py:853,880`, `daemon/verdict_report.py:33,99,193`)                   |
| `Completed/00260-.../BASH-BLINDSPOT-MAP.md`                                        | THE architecture map of why Write/Edit-keyed guards are blind to Bash writes + heredoc/redirect/tee taxonomy                                                                         | `core/utils.py:13,189,305` implements exactly this design; `HANDLER_DEVELOPMENT.md` never covers it        |
| `Completed/00272-.../RESEARCH-read-routes.md`                                      | Exhaustive inventory of every route secret content can reach context, classified RELIABLE/HEURISTIC/UNBLOCKABLE                                                                      | `secret_file_guard` shipped; neither HANDLER_REFERENCE nor CLAUDE.md carries the route inventory           |
| `Completed/00169-.../GAP-ANALYSIS.md` + `FEATURE-BACKLOG.md`                       | The project's live roadmap (HAVE/PARTIAL/MISSING vs SOTA); its #1 gap became Plan 00272 and shipped                                                                                  | No roadmap hub exists anywhere in `CLAUDE/` or `docs/`                                                     |
| `Completed/00223-.../PHASE-1-MEASUREMENT.md`                                       | Measured injection-channel semantics (SessionStart vs UserPromptSubmit delivery)                                                                                                     | `docs/guides/HANDLER_REFERENCE.md:2834` cites "the 00223 reliability finding" — a plan number with no path |
| `Completed/00216-.../PHASE-1-MEASUREMENT.md`                                       | The measure-before-you-write-the-regex methodology (34/35 FP finding)                                                                                                                | It IS this project's celebrated FP discipline; `LESSONS.md` does not carry it                              |
| `00266-.../RESEARCH-claude-code-native-hooks.md`                                   | The five native hook types + timeouts (platform knowledge)                                                                                                                           | One sentence promoted to `ARCHITECTURE.md:86`; the table was not                                           |

**Counterexamples proving promotion works when a hub exists**: Plan 00154 →
`CLAUDE/Performance/{README,BASELINE}.md` (a real hub with back-links); Plan 00203's
CRITERION.md → fully absorbed into `HANDLER_DEVELOPMENT.md:858-894`. **Systemic cause**:
the Plan Completion Checklist (`PlanWorkflow.md:~517`) has no "triage supporting docs
for promotion" step — so ~130 docs went dark by default, not by decision.

### A.7 Agents/skills carrying general documentation

- `.claude/agents/release-agent.md` (791 lines): declares `RELEASING.md` as SSoT at
  `:10`, then restates it for 780 lines — including hardcoded file+line numbers for
  version bumps (`:104-117`) — and has ALREADY drifted (missing Step 11).
- `.claude/agents/python-developer.md` (317 lines): restates the eight engineering
  principles, a general Python style guide, and the handler pattern; **actively
  contradicts** the canonical doc (`:93-101` blesses `typing.Dict/List/Optional` which
  `CLAUDE.md` and ruff's UP rules forbid). Its `:312-317` even lists the four canonical
  docs it should have pointed at.
- `.claude/agents/transcript-inspector.md` (346 lines): duplicates
  `DEBUGGING_STOP_HOOK.md`'s field tables and decision trees — and the link direction is
  *backwards* (`DEBUGGING_STOP_HOOK.md:12,378` points AT the agent file for detail).
  Also hardcodes environment paths (`/root/.claude/projects/-workspace/`), the defect
  class Plan 00244 exists to remove.
- `.claude/agents/qa-fixer.md`: carries the QA remediation cookbook that
  `CLAUDE/development/QA.md` declares itself to be — and `:238-267` instructs the agent
  to write patterns INTO `QA.md`, so it simultaneously duplicates and feeds the
  canonical doc.
- **Exemplars of the target shape**: `.claude/skills/optimise/SKILL.md` (72 lines,
  "Reference Documentation — SINGLE SOURCE OF TRUTH" section, zero copied tables) and
  `.claude/agents/hooks-daemon-plan-dedupe-scout.md` (long but entirely role-specific,
  explicitly refuses general knowledge).
- **Structural gap**: `.claude/skills/CLAUDE.md` states the no-duplication charter for
  skills; **no `.claude/agents/CLAUDE.md` exists** — and nearly every category-(c)
  violation is in `.claude/agents/`. The charter's presence/absence tracks the outcome.

### A.8 The `src/**/CLAUDE.md` escape hatch

`markdown_organization` allows `CLAUDE.md` anywhere (`markdown_organization.py:165-168`,
`:790`). Behind that hatch, 982 lines of standalone architecture documentation have
accumulated (`src/.../strategies/tdd/CLAUDE.md` 705 lines — self-declared "canonical
archetype"; `src/.../qa/CLAUDE.md` 277 lines). These may be *legitimately* canonical
(path-proximate module docs) — but nothing registers them as canonical homes, so nothing
stops a second copy growing in `CLAUDE/ARCHITECTURE.md`.

### A.9 `@`-imports

82 occurrences across 19 files, against stated policy ("avoid `@`-imports — they
re-inline eagerly"). Worst: `CLAUDE/CodeLifecycle/` quartet mutually `@`-imports itself
(pulling any one drags ~1,272 lines), and root `CLAUDE.md` carries 8 (paid every
session). The policy itself lives only inside the `markdown_organization` handler
guidance — `CLAUDE/development/DOC-CONVENTIONS.md` never mentions it. The rule has no
canonical home; predictably it is honoured nowhere.

### A.10 What the evidence says, compressed

1. **Prose summaries drift slowly and harmlessly; structured facts drift fast and
   harmfully.** Every damaging drift above is a table, a count, a step number, a command
   name, a path, or a version — not a paraphrased idea. This should shape the
   pointer-vs-duplicate boundary (Rule 4 below).
2. **Generation works; declaration-without-enforcement does not.** The generated
   surfaces (`<hooksdaemon>` block, `.claude/HOOKS-DAEMON.md`) are accurate; the two
   declared-but-unchecked SSoT charters were violated within their own subtrees.
3. **The repo already invented the right meta-rule twice** ("the script/playbook is the
   single source of truth for the list — do not restate the count", `CLAUDE.md:92`,
   `RELEASING.md` Step 12.4) — always *after* a drift incident. The ruleset should
   promote this from incident-response to standing law.
4. **Promotion fails by default, not by decision** — absence of a completion-time triage
   step, not of willingness (00154/00203 show it done well).

---

## B. Client-project drift imagination

A client repo differs from this one in every parameter the strategy currently hardcodes.
Concrete scenarios:

1. **No `CLAUDE/` tree at all.** Most clients have `README.md`, maybe `docs/`, and a
   root `CLAUDE.md` that accretes everything. Drift mode: `CLAUDE.md` becomes a 3,000-line
   junk drawer (this is what `validate_instruction_content` already fights at the
   margin). The ruleset must let the *canonical agent tree* be any configured path — or
   be "root CLAUDE.md sections" for tiny projects — exactly as `plan_workflow.directory`
   parameterises the plan tree.
2. **`docs/` is the published product.** A library whose `docs/` is a mkdocs/Docusaurus
   site has the audience split *inverted*: `docs/` is canonical human truth with CI
   building it; agent docs are the satellite. The "docs/ points at CLAUDE/ for depth"
   decision must be a *default direction*, not an axiom — config must permit declaring
   which tree owns depth per topic area, or simply which trees exist and their roles.
3. **Monorepo.** Per-package doc trees (`packages/*/docs/`, per-package `CLAUDE.md`).
   "One canonical home per fact" must be scoped: a fact about `packages/api` canonically
   lives in that package's tree. Canonical-tree config must be a list of (scope-glob →
   tree) mappings, not a single path.
4. **Template-imported agents.** Client `.claude/agents/*.md` arrive from starter kits
   carrying generic content ("You are an expert… always write tests…") that duplicates
   nothing in-repo because the repo has no canonical docs yet. A duplication checker is
   silent; only the *surface-budget/thin-pointer* heuristic (D.5) sees it. Expect this
   to be the dominant client shape — rules must degrade gracefully to "advise creating a
   canonical home", not "point at a doc that doesn't exist".
5. **Wiki/Notion/Confluence as the real SSoT.** Durable truth lives outside the repo;
   in-repo docs are all stale copies. The daemon cannot see the external tree. The
   ruleset should at least allow declaring external canonical URLs so pointers can be
   syntactically recognised (and NOT flagged as content-free), while being honest that
   external staleness is unscannable.
6. **The daemon's own footprint drifts in clients.** Clients hand-edit
   `.claude/HOOKS-DAEMON.md` or the `<hooksdaemon>` block (which regeneration then
   reverts — the v3.49.1 near-miss in reverse). The generated-doc manifest (Rule 10)
   must ship pre-seeded with the daemon's own generated artifacts in every install.
7. **Plan-folder hoarding is worse in clients.** This repo at least has `Completed/`
   discipline; the Plan 00144 origin audit of a client found 54 folders vs 41 indexed.
   Client plan folders will hold *the only copy* of architecture decisions. The
   promotion rule (Rule 8) is therefore MORE valuable in clients — and must key off the
   configured plan directory, not `CLAUDE/Plan/`.

**Therefore parameterise** (mirroring `plan_workflow.qa`): agent-tree path(s),
human-tree path(s), depth-owner direction, satellite-surface roster (which of
rules/skills/agents/sub-CLAUDE.md exist and their budgets), generated-doc manifest
(globs + optional generator command), external-canonical URL prefixes, grandfathering
allowlist, per-surface modes (off/warn/block). Ship everything OFF upstream; dogfood
here with this repo's values.

---

## C. Proposed written ruleset (draft for `CLAUDE/DocumentationStrategy.md`)

Legend: **[M]** mechanically checkable (how, in brackets) · **[J]** judgement-only ·
**[M-]** partially checkable.

**R1 — One canonical home per fact.** Every durable fact has exactly one file that owns
it; all other statements of it are pointers (R4). *Rationale: N copies makes every
change a graph traversal nobody performs (A.1).* [M-] — exact/near-exact copy detection
only (D.2/D.3); paraphrase duplication is judgement.

**R2 — The canonical agent tree is configured, defaulting to `CLAUDE/`.** Durable
agent-facing truth lives there in clearly-named files with logical sections. Facts about
a code module MAY instead live in that module's registered sub-`CLAUDE.md` (R7e), which
then IS the canonical home. *Rationale: a findable home is the precondition for
pointing.* [M] — location enforcement exists (`markdown_organization`); the new part is
the registry of module-local canonical homes.

**R3 — Audience split.** The human tree (`docs/` here) is terse and digestible and MAY
link into the agent tree for full depth; the agent tree owns depth (Decision 1). A
human-tree file that restates agent-tree content at length is a violation; summary+link
is the intended shape. The depth-owner direction is per-project config (B.2).
*Rationale: two independent renditions of one fact are two copies (A.5).* [M-] —
detectable only via D.2/D.3 cross-tree hits plus a size ratio advisory; mostly
judgement.

**R4 — The pointer test (operational boundary; answers Open Question 1).** A compliant
pointer may contain: (a) up to ~3 sentences of orientation prose saying what the target
covers and why the reader would follow it; (b) surface-specific *application* notes not
stated in the target (how THIS role/path uses the fact); (c) the link. It may NOT
contain: copied or reconstructed **tables**; **fenced command/code blocks** that appear
in the target; **numbered procedures**; **enumerated lists** duplicating the target's;
restated **normative sentences** ("MUST/NEVER…") carrying the target's rule; or
**derived facts** (R5). *Rationale: A.10.1 — the evidence shows structured facts are
what drifts harmfully; bounding restatement by CONTENT CLASS rather than sentence count
is both easier to obey and easier to check.* [M-] — the structured classes are
checkable (D.2); the 3-sentence prose bound is guidance, advisory at most.

**R4a — Safety-critical restatement exception.** A rule whose loss is dangerous (e.g.
release human-gating) may be restated in compressed prose at the point of use, but must
cite the canonical doc and still may not restate its tables/steps/counts. *Rationale:
`release/SKILL.md:34-36` shows this done right; total prohibition would be fought and
lost.* [J] — the exception is claimed in-file (e.g. an HTML comment marker), auditable.

**R5 — Derived facts are stated only by their source.** Counts, enumerated lists with a
generator, step totals, version numbers, file rosters, handler rosters: stated only in
the file/script/registry that produces them, or in a generated doc (R10). Everywhere
else: "see X, the single source of truth for the list". *Rationale: this repo's own
twice-invented meta-rule (`CLAUDE.md:92`, RELEASING.md 12.4), promoted from
incident-response to law; A.2.1/A.2.2 are the cost of not having it.* [M] — a
declared fact registry + pattern scan (D.4); the repo's existing "Doc Truth" QA check is
prior art to extend.

**R6 — Links are plain, root-relative (or verified-relative), and resolve.** No
`@`-imports outside an explicit resident allowlist (root `CLAUDE.md` deliberate
residents only); no case-mismatched paths; no links into files that do not exist.
*Rationale: A.3, A.9; `@`-imports also defeat progressive disclosure (Plan 00131).*
[M] — link-graph resolution (D.1); `@`-import census (D.8).

**R7 — Satellite surface contracts.**

- **(a) `.claude/rules/*.md`** — a delivery mechanism, not a home: trigger scope +
  pointer + brief application notes. If the substance has no canonical home yet, create
  the home first (evidence: `ccy-supervisor-dogfooding.md` carries the only copy of the
  supervisor reload contract). [M-] via D.5.
- **(b) `.claude/skills/`** — thin intent-matched pointers (`optimise/SKILL.md` is the
  exemplar). Invocation mechanics are the skill's own content; procedure bodies are not.
  [M-] via D.5 + D.2.
- **(c) `.claude/agents/*.md`** — role framing + role-unique behavioural instruction +
  pointers. No engineering-principle restatements, code skeletons, or remediation
  cookbooks. Adopt a `.claude/agents/CLAUDE.md` charter mirroring the skills one (the
  measured difference in outcomes, A.7, justifies it). [M-] via D.5 + D.2.
- **(d) sub-folder `CLAUDE.md`** — either a pure routing table (≤ ~15 lines, the
  `docs/CLAUDE.md` shape) or a REGISTERED module-local canonical home (R2). Prose
  indexes with per-file descriptions are forbidden — descriptions are duplicated facts
  and rot fastest (A.4); generate indexes or delete them. [M] — registration list +
  line budget; index-completeness check (D.6).
- **(e) code comments** — current-state rationale local to the code. Durable general
  knowledge goes to a doc, with the comment pointing at it. Already bounded by
  `comment_changelog`/`comment_size`; the "doc-in-comment" signal is advisory-only
  (Open Question 2 — see E). [J] with weak advisory heuristics.
- **(f) GitHub issues/PR bodies** — point, don't restate. The daemon sees `gh` Bash
  invocations, so a weak edit-time advisory is possible, but this is policy-first,
  enforcement-later. [J].

**R8 — Plan-folder promotion lifecycle.** Plan folders are a drafting ground. At
terminal-status flip, every supporting doc gets an explicit disposition, recorded in the
closing journal entry or a one-line frontmatter field: **promote** (content moves to the
canonical tree; a stub pointer or gutted header stays behind in the plan folder),
**historical** (the default for dated measurement snapshots — stays as-written, archive
immutability applies), or **delete**. The Plan Completion Checklist gains this step.
*Rationale: A.6 — ~130 docs dark by default; the two promotion successes both had an
explicit target hub.* [M-] — commit-gate advisory when a terminal flip stages supporting
docs with no disposition note (D.7); the promote-vs-historical call is judgement.

**R9 — Plan citations in canonical docs are provenance, not load-bearing storage.** A
canonical doc may cite `Plan NNNNN` (with a path) as history; current guidance the
reader NEEDS may not exist only behind a plan reference
(`HANDLER_REFERENCE.md:2834`'s pathless "the 00223 finding" is the anti-pattern). [M-] —
plan-number-without-path in live docs is greppable (advisory); "needs" is judgement.

**R10 — Generated docs are compliant SSoT; declare them.** A doc generated from code is
generation, not duplication — the source is the code. Every generated doc is declared in
a manifest (config: globs + generator command), pre-seeded with the daemon's own
artifacts (`<hooksdaemon>` block, `.claude/HOOKS-DAEMON.md`, generated playbooks). The
scanner exempts manifest entries from duplication checks; hand-edits to them draw an
advisory pointing at the source + regenerate command; a missing regeneration marker is a
staleness advisory. *Answers Open Question 5.* [M].

**R11 — The policy obeys itself.** `CLAUDE/DocumentationStrategy.md` is the canonical
home for these rules; root `CLAUDE.md` carries a pointer + the shortest possible
resident summary; handler `get_claude_md()` output summarises and points (and is itself
generated, hence R10-exempt). [M-] via the same checks.

**R12 — Grandfathering.** Existing violations at adoption time go into a config
allowlist (file-scoped, like `legacy_plan_allowlist`). Allowlisted files only ever
advise. Blocking applies the `plan-doc-size` tiering philosophy: only an edit that makes
things WORSE (adds a new duplicate block, adds a new dead link, grows an over-budget
surface) can block; shrinking is silent; unchanged-but-bad advises. *Rationale: A shows
dozens of standing violations; a day-one blocker would be disabled within a day (the
Plan 00214 lesson).* [M].

**R13 — Two enforcement instruments, cleanly divided.** Deterministic checks
(handler / bulk scan / sweep) enforce only the mechanically-checkable subset of these
rules: exact/near-exact copies, stale pointers, structural placement, declared
manifests and budgets. The semantic remainder — conflicting truths, paraphrase
drift, a truth scattered with no canonical home — is owned by the read-only
`hooks-daemon-docs-qa` agent (D.10), which reports with citations and never edits or
blocks. No deterministic check may attempt a semantic judgement; no rule in this
document is "enforced" merely by hoping — each is tagged with its instrument.
*Rationale: keeps the FP-discipline promise (00208/00214) — heuristic approximations
of semantic questions are exactly the rules that get handlers disabled.* [M] for the
division itself.

---

## D. Enforcement signal candidates

All modelled on `plan_qa`: pure check core, three surfaces, one config block. FP
assessments are grounded in the part-A sample.

**D.0 Division of labour (scope update, user-directed).** Enforcement is split into
two halves and each signal below is tagged with its owner:

- **[DETERMINISTIC]** — handler / bulk scan / sweep. Owns only the mechanically
  checkable subset: exact/near-exact copies, stale pointers, structural placement,
  declared-manifest checks. If a check needs to understand what a sentence MEANS, it
  does not belong here — do not contort a semantic judgement into a regex (the
  part-A evidence shows the harmful drift is mostly structural anyway, so the
  deterministic half is genuinely load-bearing, not a consolation prize).
- **[AGENT]** — the `hooks-daemon-docs-qa` read-only agent (deployed via the Plan
  00279 generic agent install subsystem, `hooks-daemon-plan-dedupe-scout`-style).
  Owns conflicting truths (two docs asserting incompatible facts), paraphrase
  drift, and truths scattered across surfaces with no canonical home. It cites
  file:line, never edits, never blocks. See D.10 for its design.

The split resolves the tension running through D.2–D.5 below: each of those signals
has a deterministic CORE (hash equality, size, declared facts) and a semantic
PENUMBRA (paraphrase, "is this restatement or application note?", "do these two
sentences contradict?"). The deterministic surface ships the core; the penumbra is
reassigned to the agent rather than approximated with fragile heuristics.

Ownership summary:

| Signal                                                      | Owner                                                                                                               |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| D.1 pointer-resolves                                        | DETERMINISTIC (edit-time + bulk + sweep)                                                                            |
| D.2 no-duplicate-block (exact/near-exact structured blocks) | DETERMINISTIC (bulk/sweep; edit-time via cached index)                                                              |
| D.3 paraphrase drift / conflicting truths                   | AGENT (deterministic shingling demoted to an optional pre-filter)                                                   |
| D.4 derived-fact-drift                                      | SPLIT — registered-fact pattern scan DETERMINISTIC; unregistered contradictions AGENT                               |
| D.5 surface-budget / thin-pointer                           | SPLIT — size tiers + doc-marker headings DETERMINISTIC (advisory); "is this restatement or application note?" AGENT |
| D.6 index-completeness                                      | DETERMINISTIC                                                                                                       |
| D.7 plan-promotion-triage                                   | DETERMINISTIC trigger (commit gate); promote-vs-historical judgement AGENT/human                                    |
| D.8 no-new-at-imports                                       | DETERMINISTIC                                                                                                       |
| D.9 generated-doc-hand-edit                                 | DETERMINISTIC                                                                                                       |
| Scattered truth with no canonical home                      | AGENT only — no deterministic shape exists                                                                          |

**D.1 `pointer-resolves` (stale links).** [DETERMINISTIC]
Detects: markdown links + `@`-imports + (optionally) backticked repo paths whose target
does not exist on disk; case mismatches on case-sensitive targets.
Surfaces: edit-time (only links present in the written content — a handful of `stat`
calls, well under any latency budget), bulk scan, sweep.
FP assessment: real, but well-understood — placeholder/example links
(`docs/PLAN_SYSTEM.md:287-291`, template `NNNNN-`/`XXX`/`vX.Y.Z` tokens), links inside
fenced *example* blocks, archived plans (exclude `Completed/`, matching the
`path-existence` precedent that archives are records). Mitigation: skip targets
containing placeholder tokens (`{`, `NNNNN`, `X.Y.Z`, `*`, `<`); anchor-only and
external links skipped or existence-only. Plain-markdown-link resolution can go
`warn`→`block` for NEW links; backticked-path checking stays advisory (prose mentions
are often deliberately historical — the `path-existence` lesson).
Cost: trivial. **Recommend: ship first — highest value/risk ratio; A.3 shows seven
standing hits.**

**D.2 `no-duplicate-block` (verbatim/near-verbatim structured duplication).**
[DETERMINISTIC — its ambiguous hits are handed to the agent for adjudication, D.10]
Detects: a fenced code block, table, or numbered-list run ≥ N lines (suggest 5) whose
normalised hash appears in 2+ non-generated doc-surface files.
Surfaces: bulk scan + sweep primarily. Edit-time is feasible against an in-memory index
built at daemon startup/sweep (hash lookup per block — microseconds); index staleness
between sweeps is acceptable for an advisory.
FP assessment — measured against part A: it would correctly catch the byte-identical
tier tables (`CLAUDE.md:583-587` = `HANDLER_DEVELOPMENT.md:152-154`) and the skill/agent
restatements; it would ALSO fire on the `./bin/hooks-daemon restart` + `status`
verification block, present in six files as *deliberate house style* (A.2 finding 15).
That is a true positive under R4 but the project may choose to keep it — so either an
`idiom_allowlist` of short blessed snippets, or a higher line threshold for
command-fence blocks. **Recommend: advisory-only until a whole-repo run is
hand-triaged (00208/00214 discipline), then block only on NEW duplicates (R12).**

**D.3 near-duplicate paraphrase + conflicting truths.** [AGENT]
Detects: paragraph-level near-copies (the `python-developer.md` principles restatement —
"same eight, same order, different wording" — is invisible to D.2), and the harder case
D.2 can never see: two docs asserting INCOMPATIBLE facts (the acceptance-test skill vs
GENERATING.md inversion, the three priority-band schemes).
Ownership: this is the docs-qa agent's core mandate. A deterministic shingling/minhash
pass has FPs by construction (two docs legitimately discussing one topic in their own
scope shingle-overlap) and, crucially, cannot distinguish "duplicate" from
"contradiction" — the distinction that matters most (a contradiction is worse than a
copy). **Recommend: do NOT ship deterministic shingling as a recurring gate. At most,
keep a cheap shingle pass as an internal PRE-FILTER the agent's orchestration can use to
shortlist candidate file pairs for a large tree (D.10) — its FPs then cost agent
attention, not user trust. Answers Open Question 4: exact-block edit-time via cached
index; everything softer than exact goes to the agent.**

**D.4 `derived-fact-drift` (R5 enforcement).** \[SPLIT — registered facts
DETERMINISTIC; unregistered factual contradictions belong to the agent\]
Detects: a stated value of a registered derived fact (QA check count, handler count,
current version, step totals, venv path shape) that disagrees with its generator; and
optionally ANY numeric claim adjacent to a registered fact's keywords outside the source
file.
Surfaces: bulk scan + sweep; edit-time for the registered patterns (regex vs cached
values — cheap). Prior art: the QA suite's existing Doc Truth check and
`check_repo_hygiene`'s `unreleased-manifest-date` rule (I did not audit their
implementations; Phase 2 should extend rather than duplicate them — the check family
already has a home in `scripts/qa/`).
FP assessment: the killer FP is *quoted history* — `CLAUDE.md:92` itself says "it
drifted to 10 while the suite ran 13", which a naive scanner flags twice. Mitigations:
skip values inside quotation marks/parenthetical history, per-fact line allowlist.
**Recommend: advisory; block only for a small hand-picked fact set (current version
string in non-RELEASES docs is nearly FP-free).**

**D.5 `surface-budget` / thin-pointer heuristic (R7, Open Question 3).** \[SPLIT —
size tiers + marker headings DETERMINISTIC advisory; the restatement-vs-application
judgement is the agent's\]
Detects: a skill body / agent file / rules file exceeding a size tier, OR containing
"general-doc" markers (headings like `## Engineering Principles`; ≥2 D.2 duplicate
hits; fenced code skeletons in an agent file).
Surfaces: edit-time (size + markers are per-file, cheap) + sweep.
FP assessment: size alone is weak — `hooks-daemon-plan-dedupe-scout.md` (226 lines) is
legitimately long and entirely role-specific, while `qa-runner.md` (162 lines) is a
violation. So: size is only ever the *advisory tier trigger*, and the plan-doc-size
grow-only tiering applies (an over-budget agent file can always be edited smaller;
only growth blocks, and only in `block` mode with a `MUST_EXCEED_..._BECAUSE` escape).
Combining size with D.2 hits gives the honest signal. **Recommend: advisory, tiered;
never block on size alone.**

**D.6 `index-completeness`.** [DETERMINISTIC]
Detects: a file declaring itself an index of a directory (opt-in frontmatter
`indexes: <dir>`, or the R7d registration) whose listing disagrees with the directory.
Surfaces: sweep + bulk.
FP assessment: near-zero when declared (the check is set-difference); do NOT infer
indexhood heuristically from phrases like "Files in This Directory" — that guess is
where FPs live. **Recommend: mechanical and safe, but pair it with R7d's real fix:
delete or generate prose indexes.**

**D.7 `plan-promotion-triage` (R8).** \[DETERMINISTIC trigger; disposition judgement
stays with the closing agent/human — the docs-qa agent can audit past dispositions\]
Detects: commit staging a terminal-status flip for a plan whose folder contains
supporting docs (non-PLAN/JOURNAL/CRITIQUE/REVIEW) with no disposition note staged.
Surfaces: commit gate (extends `plan_qa`'s `terminal-state-atomic` family) + sweep
(archived plans whose docs carry a `promote` disposition never executed).
FP assessment: low — the trigger is structural, not semantic; the agent satisfies it
with one line per doc. Wrong dispositions (marking everything `historical`) are
un-checkable, but the forcing function is the point: A.6 shows the failure is absence
of the question, not wrong answers. **Recommend: advisory in the commit gate from day
one (it composes with the existing plan_qa gate rather than a new handler).**

**D.8 `no-new-at-imports`.** [DETERMINISTIC]
Detects: an `@`-style import added outside the allowlist. Skip backtick-quoted
occurrences (the `CLAUDE/QA.md` quoted-lint-rule FP found in A.9).
Surfaces: edit-time + bulk. Cost: trivial. FP: low with the backtick guard.
**Recommend: advisory, then block for NEW files; existing 82 occurrences grandfathered.**

**D.9 `generated-doc-hand-edit` (R10).** [DETERMINISTIC]
Detects: Write/Edit to a manifest-declared generated doc → advisory naming the source
and regenerate command; sweep checks the regeneration marker/version for staleness.
FP: essentially zero (the manifest is explicit; the daemon's own auto-commit path can be
recognised or simply tolerated as advisory). **Recommend: ship early; protects clients
from the B.6 scenario.**

**D.10 The `hooks-daemon-docs-qa` agent (semantic half — design recommendation).**

*Deployment*: read-only agent via the Plan 00279 generic agent install subsystem;
`hooks-daemon-plan-dedupe-scout` is the template for tone and self-restraint (it
explicitly refuses to carry general knowledge and reports candidates with reasons,
never a verdict — both properties transfer directly).

*Scan strategy for large doc trees* (it cannot read everything into one context):

1. **Inventory pass, not content pass.** First build a cheap map from tool output,
   not file reads: the configured surface roster (canonical trees, satellites),
   file sizes, and headings (`Grep` for `^#{1,3} ` per file). Headings are the
   topic index — the part-A drift clustered under nameable topics (QA commands,
   release steps, priority bands, venv paths), each discoverable from headings and
   a handful of keyword greps.
2. **Topic-sharded deep reads.** For each candidate topic (heading co-occurrence
   across 2+ files, or a keyword hit list), read ONLY the implicated sections/files
   and adjudicate: same fact? which copy is canonical? do they agree? This bounds
   per-topic context regardless of tree size. For trees too large even for the
   inventory in one context, the agent dispatches per-topic sub-readers if its
   harness allows, or processes topics in sequence and appends findings as it goes.
3. **Deterministic pre-seed.** Feed it the bulk scanner's machine findings
   (D.1/D.2/D.4 output) as its starting worklist — the agent's judgement is most
   valuable ADJUDICATING mechanical hits (true duplicate vs blessed idiom vs
   application note) and extending from them to the paraphrase/contradiction
   neighbours the machine cannot see. This also keeps repeat runs cheap: triage the
   delta, not the corpus.
4. **Freshness tiebreaker without guessing**: when two copies disagree, `git log -1 --format=%cI -- <file>` per copy tells it which copy moved last — usually the
   migrated-forward truth (A.1's pattern: the canonical docs were updated, the
   satellites were not). Report the evidence, not a unilateral verdict on which is
   "right" — that call is the human's, exactly as the dedupe-scout does.

*Report format*: one markdown report file (the `idle_housekeeping` convention:
`untracked/reports/` by default; a plan folder when run for a plan). Per finding:
**id** (stable slug so re-runs can diff), **class** (`conflicting-truth` |
`paraphrase-duplicate` | `scattered-truth-no-home` | `adjudicated-mechanical-hit`),
**severity** (conflict > duplicate > scatter), **each copy as file:line + a ≤2-line
quote**, **which copy the evidence suggests is current** (with the git-date evidence),
and **suggested remediation** (which file becomes/holds the canonical home, which
copies become pointers). Plus a summary table and an explicit "adjudicated as fine"
list — recording NON-findings is what stops the next run re-litigating them, and is
the grandfathering input for the deterministic allowlist.

*Invocation routes* (all three, they compose):

1. **On-demand** — the primary route: a human or the executing agent dispatches it
   (Task 1.2's dogfood migration should be its first real run — the report IS the
   migration worklist, and doubles as the agent's acceptance test against part A of
   this review: it should independently rediscover A.1, A.2.2, A.2.6).
2. **Sweep-suggested** — the SessionStart docs sweep, when it has findings past a
   threshold (or a staleness clock since the last report), ADVISES dispatching the
   agent; it never auto-dispatches (a SessionStart hook must stay cheap, and
   spawning agents is the session's call — same restraint as `plan_number_helper`'s
   dedupe-scout suggestion, which is explicitly "a SUGGESTION — it never blocks").
3. **Idle-housekeeping specialist** (Plan 00161 / `idle_housekeeping_advisory`) —
   register it in the housekeeping roster: report-only, read-only, strictly lower
   priority than real work. This is the natural periodic route for clients since it
   costs an idle session, not a working one.

Cadence guard: whatever the route, rate-limit by report freshness (skip if a report
younger than N days exists and the doc tree's git mtime has not advanced) — the
corpus changes slowly and semantic re-scans are the expensive half.

**Latency note for the edit-time surface**: D.1/D.4/D.5/D.8/D.9 are per-file
regex+stat work — comfortably inside the daemon's ~1.8 ms dispatch envelope's order of
magnitude. D.2 edit-time requires the in-memory corpus index; if index build proves
expensive at startup, D.2 stays batch-only with no great loss.

---

## E. Open questions requiring the human's judgement

1. **Depth-owner axiom vs parameter.** Decision 1 fixes "docs/ points at CLAUDE/ for
   depth" for THIS repo. For clients whose `docs/` is the published product (B.2), that
   direction is wrong. Options: (a) hardcode the direction, accept misfit; (b) make
   depth-owner a config choice per tree. **Recommendation: (b)** — same instinct as
   `plan_workflow.directory`; this repo's config states the user's direction verbatim.
2. **Is the six-fold daemon-restart snippet house style or a violation?** D.2 will flag
   it honestly. Options: bless it via an idiom allowlist; or consolidate to one home
   and point. **Recommendation: consolidate** — it is exactly the shape that drifted
   everywhere else — but this changes six revered files, so it is the human's call.
3. **Fate of the heavyweight `docs/` trio** (`PLAN_SYSTEM.md` 1,580 lines,
   `QA-INFRASTRUCTURE.md`, `QA-RUNNER-SETUP.md`): merge-and-delete, or gut to
   summaries+links. Content decisions with user-visible surface area — human scope
   call for the dogfood-migration task. **Recommendation: gut PLAN_SYSTEM.md to a
   human-facing overview pointing at PlanWorkflow.md; fold the QA pair into one
   accurate human doc.** Same call needed for `CONTRIBUTING.md`'s drifted skeleton
   (A.2.4) — external-contributor-facing, so wording matters.
4. **`src/**/CLAUDE.md` escape hatch (A.8).** Register the two big module docs as
   canonical homes (R2/R7d) or migrate them into `CLAUDE/Architecture/`?
   **Recommendation: register** — path-proximate module docs are genuinely useful and
   the registry closes the governance gap — but cap the hatch: unregistered
   sub-CLAUDE.md files above the routing-table budget draw an advisory.
5. **Handler shape (Task 1.3).** Extend `markdown_organization` (already 1,123 lines,
   owns *location*) vs a sibling `docs_qa` core + thin handlers. **Recommendation:
   sibling package `docs_qa/` on the plan_qa template** — location and
   duplication/pointer integrity are different concerns with different check shapes
   (cross-file, corpus-indexed); `plan_qa` proves the pattern; `markdown_organization`
   keeps location + memory policy and gains only a pointer to the new policy doc. One
   shared config block (`documentation:` or `docs_workflow.qa:`) governs both, so the
   two handlers cannot fragment the policy (the Plan 00144 Decision 3 argument).
6. **Blocking ambition.** Even the best checks here (D.1 new-link resolution, D.9)
   should ship advisory and be ratcheted per the 00144 precedent (its commit gate is
   STILL warn-mode pending a human go/no-go). Confirm the intended end-state: is
   anything in docs-qa ever meant to reach `block` in client repos, or is
   advisory+CI-exit-code the ceiling? **Recommendation: block-capable but
   default-warn forever upstream; `block` is a per-project ratchet like
   `commit_gate_mode`.**
7. **Comment signal (plan Open Question 2).** No cheap low-FP "durable knowledge in a
   comment" signal survives contact with the evidence — the discriminator (would a
   future reader elsewhere need this?) is semantic. `comment_changelog`/`comment_size`
   already bound the worst shapes. **Recommendation: judgement-only guidance in
   DocumentationStrategy.md; no new comment check.**

### Answers to the plan's five Open Questions, in one line each

1. *Pointer vs duplicate*: bound by CONTENT CLASS, not sentence count — ≤3 orientation
   sentences plus surface-specific application notes are a pointer; any copied
   table/fence/procedure/enumeration/derived-fact is a duplicate (R4, R5).
2. *Comments*: judgement only — no deterministic check; in-scope for the docs-qa
   agent's sweep where a comment plainly carries a doc-owned truth (E.7).
3. *Agents/skills*: size-tier trigger + duplication hits + doc-marker headings as
   the DETERMINISTIC advisory (D.5, grow-only tiering); the restatement-vs-role-note
   judgement goes to the docs-qa agent; plus an agents charter file (R7c).
4. *Detection method*: link-graph + exact-block-hash fit edit-time (with a cached
   index); everything softer than exact — paraphrase, contradiction — is the
   docs-qa AGENT's mandate, not a batch heuristic (D.3, D.10).
5. *Generated docs*: explicit manifest, pre-seeded with the daemon's own artifacts;
   manifest entries exempt from duplication, checked instead for hand-edits and
   staleness (R10, D.9).
