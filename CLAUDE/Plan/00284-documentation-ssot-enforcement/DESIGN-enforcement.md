# Phase 2 Design — docs_qa enforcement architecture

Supporting doc for Plan 00284 (Tasks 2.1–2.5). Grounded in the shipped
`plan_qa` package (Plan 00144), `CLAUDE/DocumentationStrategy.md` (the binding
ruleset, R1–R13), `REVIEW-fable.md` §D (signal assessments + §D.10 agent
design) and `RULESET-sub-claude-md.md` (module-doc registry + budgets).

## 2.1 The check core: package `docs_qa/`

Sibling of `plan_qa/`, mirroring its layout (Decision 5):

```
src/claude_code_hooks_daemon/docs_qa/
├── __init__.py
├── types.py        # Finding, Severity, CheckStage (EDIT | STAGED | SWEEP)
├── context.py      # CheckContext: edited file + would-be content | staged set | tree
├── corpus.py       # DocCorpus: inventory, link graph, quote index, block-hash index
├── policy.py       # plain-values mirror of the typed config (plan_qa/types.py pattern)
├── report.py       # advisory/deny rendering, shared remedy text
├── runner.py       # stage orchestration, per-check mode resolution
└── checks/         # one module per check, declarative registry (plan_qa pattern)
```

**The corpus index is the piece plan_qa does not have.** Cross-file checks
(link resolution, quote drift, duplicate blocks) need a whole-tree view that
cannot be rebuilt per keystroke. `corpus.py` maintains a cached index under
`untracked/docs-qa/index.json`:

- built lazily on first use; invalidated per-file by mtime+size (the
  `lint_on_edit` cache pattern);
- stores per doc: outbound links (path + anchor), headings/anchors, ssot-quote
  blocks (source ref + normalised quote hash), normalised block hashes
  (fences, tables, list runs ≥3 items — the R4 structured classes), size/line
  counts;
- a reverse index: source-file → its quoters, target-file → its linkers, so
  editing a SOURCE can cheaply surface stale quoters/linkers.

Normalisation before any comparison: run BOTH sides through the actual
mdformat-gfm pipeline `markdown_table_formatter` uses — whitespace collapse
alone equates neither its asterisk escaping (`*` → `\*`) nor its ordered-list
renumbering, so anything weaker false-drifts on formatter churn.

**Cold/stale-index rule (critique MUST-2)**: no block-eligible check may DENY
on a cold or unvalidated-stale index — it degrades to advisory or skips, with
the sweep as the backstop. The index is built/refreshed at daemon startup or
SessionStart, never lazily inside a PreToolUse budget; `index.json` writes are
atomic-replace (multiple sessions share one daemon — the status-line writer
concurrency rules apply to this file too).

**Corpus scope**: `CHANGELOG.md`, `RELEASES/`, and `CLAUDE/Plan/Completed/`
are EXCLUDED from duplicate-block and link-graph traversal — archives are
records and the changelog legitimately restates everything; unscoped, the
index balloons and the false positives are guaranteed.

### The deterministic checks (R13-scoped; each names its stages and block-eligibility)

| check id                     | detects                                                                                           | stages               | block-eligible?                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------ |
| `pointer-resolves`           | link to missing file/anchor; case-mismatched path                                                 | EDIT, STAGED, SWEEP  | yes — NEW links only                                                           |
| `quote-drift`                | ssot-quote block ≠ its source span (2.4)                                                          | EDIT, STAGED, SWEEP  | yes — on the QUOTING edit                                                      |
| `quote-source-stale`         | editing a SOURCE span that has quoters (reverse index)                                            | EDIT (advise), SWEEP | never (advisory hand-off)                                                      |
| `rules-file-shape`           | `.claude/rules/*.md` violating pointer-only form (R7a): fences/tables/procedures/over-budget body | EDIT, SWEEP          | yes (Decision 6's example)                                                     |
| `rules-file-orphan-shrink`   | a rules-file shrink staging no same-commit canonical growth (promotion guard, RULESET §3)         | STAGED               | never                                                                          |
| `generated-doc-hand-edit`    | Write/Edit to a manifest-declared generated doc; SWEEP: regeneration-marker/hash freshness        | EDIT, SWEEP          | yes (EDIT only)                                                                |
| `duplicate-block`            | a structured block (R4 classes) hash-identical to one in a canonical doc, outside an ssot-quote   | EDIT, SWEEP          | never at first (00208/00214: hand-triaged whole-repo run before any promotion) |
| `at-import-census`           | `@`-import outside the root-CLAUDE.md resident allowlist (R6)                                     | EDIT, SWEEP          | yes — NEW imports only                                                         |
| `module-doc-budget`          | unregistered sub-CLAUDE.md over routing budget; registered one crossing size tiers (RULESET §2)   | EDIT, SWEEP          | grow-only, top tier only                                                       |
| `plan-promotion-disposition` | terminal-status commit staging supporting docs with no disposition note (R8)                      | STAGED               | never                                                                          |

Every check: grandfather allowlist honoured (R12), grow-only tiering where
sized, remedy text naming the exact fix (plan_qa's `remedy.py` discipline).

**Per-check refinements from the design critique** (all applied):

- `pointer-resolves` block scope: block-capable ONLY for NEW plain markdown
  links whose target FILE is missing. Anchor resolution is advisory-only until
  the slug algorithm has soaked (slug variance is real); backticked prose
  paths are advisory-only always; placeholder-token targets (`NNNNN`,
  `X.Y.Z`, `{…}`, `*`, `<…>`) and example fences are skipped.
- `rules-file-shape` applies R12 worse-only semantics STRUCTURALLY, not just
  via allowlist: deny only an edit that ADDS a forbidden element or grows the
  body; shrinking is silent; unchanged-but-fat advises. Every client with
  template rules files starts non-compliant (this repo's two both fail the
  contract today), so a naive day-one deny would fire on unrelated typo fixes.
  The thinning edits themselves pass by construction.
- `generated-doc-hand-edit` gains a SWEEP half (regeneration-marker/hash
  freshness) — a write-time-only guard cannot see a Bash-redirect hand-edit or
  one made before enablement (Core Standard 15 corollary).
- `at-import-census` skips backtick-QUOTED occurrences — docs legitimately
  quote `@`-import strings when describing the rule itself.

**R5 (derived facts) tracing**: its deterministic half is the EXISTING
`doc_truth` QA check in `scripts/qa`, extended with a declared fact registry —
sweep-stage at most, not a new docs_qa check; unregistered contradictions are
the agent's half. Also traced so absence reads as decision, not omission:
R9's plan-citation-without-path is a sweep advisory folded into
`pointer-resolves`; R4a marker audit is judgement-only (agent); R3 has no
dedicated check — it is enforced by cross-tree `duplicate-block` hits + agent
judgement, with `markdown_organization` keeping the location half (the
`trees:` config keys exist for THOSE consumers, not for a check of their own);
agent/skill file SIZE has no deterministic signal (only `module-doc-budget`
survived review) — deliberately left to the agent's thin-pointer judgement.

## 2.2 The three surfaces + config

Thin consumers of the core, exactly the plan_qa trio:

- **`docs_qa_edit`** (PreToolUse, Write/Edit + Bash-authored `.md`): runs
  EDIT-stage checks on the content the file WOULD have. Mode per check.
- **`docs_qa_commit_gate`** (PreToolUse on `git commit`): STAGED-stage checks
  over the staged tree.
- **`docs_qa_sweep`** (SessionStart): SWEEP once per session, advisory only,
  silent when clean. When drift is found it may SUGGEST dispatching the
  docs-qa agent (never auto-dispatch).
- **CLI**: `hooks-daemon docs-qa --sweep | --lint <file> | --check-staged`
  (+ `--json`), exit 1 on findings — the CI hook.

**Config parsing follows the real plan_qa precedent** (critique SHOULD-3):
the typed pydantic model `DocumentationConfig` lives in `config/models.py`
(`extra=forbid`, central validation) exactly as `PlanWorkflowConfig.qa` does;
`docs_qa/policy.py` carries only a plain-values mirror. No in-package YAML
parsing.

**Config block** — top-level `documentation:` (the plan_workflow precedent),
one shared home so the handlers cannot fragment policy (Decision 5):

```yaml
documentation:
  enabled: false            # ships OFF upstream; this repo turns it on (dogfood)
  trees:
    agent: CLAUDE           # names are config; the split is not (Decision 1)
    human: docs
  qa:
    edit_mode: warn         # warn | block — default for EDIT-stage checks
    commit_gate_mode: warn
    sweep_mode: advise
    check_modes: {}         # per-check override, e.g. rules-file-shape: block
    grandfather_allowlist: []    # file globs; advise-only forever (R12)
    generated_docs:              # R10 manifest, pre-seeded by the daemon
      - {glob: ".claude/HOOKS-DAEMON.md", generator: "bin/hooks-daemon generate-docs"}
    registered_module_docs: []   # RULESET §2 registry (R2/R7d)
    resident_at_imports: ["CLAUDE.md"]   # R6 allowlist
```

Block eligibility is enforced structurally: a check not marked block-eligible
ignores a `block` override (fuzzy signals can never deny — R13).

## 2.3 The `hooks-daemon-docs-qa` agent

Shipped via the Plan 00279 agent install subsystem (version + md5 ledger,
customisation detection, config-gated deploy). Design per review §D.10:

- **Read-only**; reports, never edits, never blocks.
- **Scan strategy**: inventory pass (sizes + headings via Grep — headings are
  the topic index) → topic-sharded deep reads of implicated sections only,
  bounding context per topic regardless of tree size. Pre-seeded worklist:
  the deterministic scanner's findings (`docs-qa --sweep --json`), so its
  judgement adjudicates mechanical hits and radiates outward. Git last-commit
  dates per copy are the freshness tiebreaker; it reports evidence, never a
  unilateral verdict.
- **It owns the semantic half** (R13): conflicting truths, paraphrase drift,
  scattered-truth-with-no-home, and — Decision 7 — it EXPLICITLY hunts
  verbose comment blocks (fed by the skill's finder scripts) and treats them
  as documentation to cross-check.
- **Report**: one markdown file in `untracked/reports/` (idle-housekeeping
  convention). Per finding: stable id, class (`conflicting-truth` |
  `paraphrase-duplicate` | `scattered-truth-no-home` |
  `adjudicated-mechanical-hit` | `doc-in-comment`), severity (conflict >
  duplicate > scatter), file:line with ≤2-line quotes per copy, which copy the
  evidence says is current, suggested remediation. PLUS an
  "adjudicated as fine" list — non-findings that stop re-litigation on
  re-runs and feed the grandfather allowlist.
- **Invocation** (all three compose): on-demand dispatch (primary — its first
  real run is the Task 3.2 dogfood migration, doubling as its acceptance
  test); sweep-SUGGESTED; registered as a Plan 00161 idle-housekeeping
  specialist. Rate-limited by report freshness vs doc-tree git mtime.

## 2.4 The `ssot-quote` mechanism (Decision 2)

Markup (works in any surface that tolerates HTML comments — .md everywhere):

```markdown
<!-- ssot-quote: CLAUDE/SomeDoc.md#daemon-restart-verification -->
(verbatim excerpt)
<!-- /ssot-quote -->
```

- **Anchor**: ONE heading-slug algorithm pinned in code, with explicit
  `<!-- ssot-anchor: name -->` markers PREFERRED for anything non-trivial —
  this repo's headings carry emoji and colons ("🚨 CRITICAL: …"), where slug
  implementations disagree. Never line numbers. The addressed span is the
  anchor's section (to the next heading of same or higher level, or the
  closing marker).
- **Verification**: the quote body, normalised, must be a contiguous
  substring of the normalised source span. Robustness requirements (critique
  MUST-1): (i) normalisation runs BOTH sides through the same mdformat-gfm
  pipeline the table formatter uses; (ii) section-span extraction is
  FENCE-AWARE via a markdown parser — a `# heading`-looking line inside a
  code fence must not terminate the span, and ssot markers inside fences do
  not count; (iii) a documented MINIMUM quote length (a one-line quote is a
  substring of almost anything — it verifies trivially and protects nothing);
  (iv) a quote must come from a SINGLE section — verbatim text spanning two
  sections fails by construction, documented so authors do not fight it.
  EDIT-stage on the quoting file (`quote-drift`, block-eligible); editing the
  SOURCE advises which quoters now need re-checking (`quote-source-stale`,
  section-hash diff of would-be vs on-disk content); SWEEP re-verifies all.
- **Budgets**: quoted blocks are excluded from module-doc size budgets
  (RULESET §2), removing the perverse incentive to point when quoting is
  safer. Rules files get no such exclusion — R7a forbids quotes there
  outright.
- **Adoption seed**: the six-fold daemon-restart snippet converts to quotes
  of one canonical section during the Task 3.2 migration. The canonical
  section lives OUTSIDE any generated block (natural owner:
  `CLAUDE/CodeLifecycle/General.md`) — quoting a generated span would tie
  every quoter to regeneration churn.

## 2.5 The docs-qa skill (shim)

`hooks-daemon` deploys a `docs-qa` skill whose ONLY job is fronting the agent
(user direction: "a shim/helper for the docs qa sub agent"):

- `SKILL.md`: intent triggers ("audit the docs", "conflicting truths",
  "docs drift") + dispatch instructions for the `hooks-daemon-docs-qa` agent +
  pointer to `CLAUDE/DocumentationStrategy.md`. No doc body of its own (skills
  charter).
- `scripts/`: deterministic finders the agent (or a human) runs —
  `find-comment-blocks` (long comment blocks per language, feeding Decision
  7's hunt), plus thin wrappers over `hooks-daemon docs-qa --sweep --json`.
  Finders list candidates; they never judge and never gate.

## Phase 3 implementation order (risk-ranked, per review §D)

1. `pointer-resolves` + corpus link graph (trivial cost, seven standing hits,
   best value/risk) + the CLI skeleton.
2. `generated-doc-hand-edit` + manifest config.
3. `rules-file-shape` (crisp; the Decision 6 block exemplar) + charter files.
4. `ssot-quote` (2.4) + restart-snippet migration.
5. Budgets/registry; `at-import-census`; STAGED checks.
6. `duplicate-block` — advisory only, AFTER a hand-triaged whole-repo run.
7. Agent + skill; dogfood migration run (Task 3.2) as the acceptance test.

Each step: TDD, daemon restart verification, client-mode fixture check,
QA gate — per CLAUDE/CodeLifecycle/Features.md.
