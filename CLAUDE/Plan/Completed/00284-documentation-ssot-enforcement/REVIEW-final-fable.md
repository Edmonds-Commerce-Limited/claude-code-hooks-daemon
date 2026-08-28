# Post-Completion Fable Review — Plan 00284 (Documentation SSoT Enforcement)

> **Note on provenance**: this is a post-completion review deliberately added to an
> archived plan as a dated record (per the archive-immutability convention, a NEW
> supporting document recording a later review is permitted; nothing pre-existing
> was edited). It is the post-implementation counterpart to `REVIEW-fable.md`
> (the Task 1.1 pre-implementation review). Reviewer: Fable-class agent,
> dispatched by the coordinating session at the repository owner's request.

## 1. Verdict

**GOOD WITH NITS — ready for release, with a short pre-release punch list.**

The delivered system is design-sound: it faithfully implements the R1–R13 ruleset
and all seven recorded user decisions, the plan_qa architectural template was
followed cleanly (pure check core, three thin surfaces, one config block,
CI-able CLI), test coverage over `docs_qa/` is 99.3% with a test file per module
and per check, the dogfood migration genuinely happened (sweep verified live at
exactly the claimed 34 advisories), and everything ships OFF by default so no
client is exposed involuntarily. However, four small, mechanical defects should
land **before the staged v3.57.0 manifest promotes `documentation.enabled` with
`recommended: true`** — two behavioural defects in the delivered checks (CLI
severity inflation; two checks ignoring the grandfather allowlist), one
real-world client scaling hazard (no vendored-dependency exclusion inside the
configured trees plus an unpruned whole-repo walk every session start), and one
documentation gap (the three handlers are entirely absent from
`docs/guides/HANDLER_REFERENCE.md` and the whole `docs/` human tree). None
requires design rework; all are bounded fixes. If they cannot land before
release, the honest alternative is downgrading the manifest promotion to
`recommended: false` until they do.

## 2. What was verified, and how

- **Read**: PLAN.md, `CLAUDE/DocumentationStrategy.md` (R1–R13),
  DESIGN-enforcement.md (structure vs delivered checks), REVIEW-fable.md
  (section survey), TRIAGE-duplicate-block.md and AUDIT-dogfood-run-1.md
  (follow-up scan), the closing JOURNAL entry, the dogfood config block in
  `.claude/hooks-daemon.yaml`, the v3.57.0 config-changes manifest, Plan 00286,
  and the plan-index README rows/statistics.
- **Ran**: `bin/hooks-daemon docs-qa --sweep` — exit 1 (CI-able), **exactly 34
  advisories** (16 pointer-resolves, 8 at-import-census, 7 module-doc-budget, 3
  duplicate-block), matching the plan's closing claim. `pytest tests/unit/docs_qa/ -q` — **339 passed** in 3.6 s.
- **Delegated + independently spot-verified**: a full code-quality review of the
  `docs_qa` package, the three handlers and the CLI (99.31% coverage measured;
  key findings below reproduced empirically by the reviewer, and the two most
  severe re-verified by me directly against `daemon/cli.py:4371-4378`,
  `checks/rules_file_shape.py:239-243`, `checks/module_doc_budget.py:164-166`,
  and a grep proving `at_import_census.py`/`module_doc_budget.py` never consult
  `grandfather_allowlist`); and a client-projection analysis of scope
  resolution, tree-config handling and the shipped agent/skill assets.
- **Checked coherence**: README index carries correct rows for both 00284 and
  00286 (with 00132 marked superseded by 00284 and the cancelled count
  updated); the closing journal entry records R8 dispositions (HISTORICAL) for
  all five supporting docs; `.claude/HOOKS-DAEMON.md` staleness (see nit N6).

## 3. Findings

### 3a. Fix before the v3.57.0 client promotion (release-blocking for `recommended: true`)

**F1 — `docs-qa --lint` inflates every worse-only finding to BLOCK.**
`daemon/cli.py:4371-4378` builds the EDIT context with `file_exists_before=True`
but **no `file_content_before`**. Every worse-only check then treats the
on-disk state as entirely new: `rules_file_shape.py:239-243` compares against
`_EMPTY_METRICS`, `module_doc_budget.py:164-166` forces `grows = True`, and
`pointer_resolves.py`/`at_import_census.py` treat every existing link/import as
newly added. Reproduced: an unchanged, already-violating `.claude/rules` file
reports `BLOCK` from the CLI and `ADVISE` from the handler for identical
content — contradicting the checks' own docstrings, mislabelling severity in
the very tool the manifest's migration note tells clients to triage with, and
collapsing the R12 worse-only tiering entirely for any project that ratchets a
check to block mode (CI on `--lint` would fail on grandfathered state).
*Fix*: pass `file_content_before=lint_content` in `cmd_docs_qa` (an on-disk
lint has, by definition, no pending change).

**F2 — `grandfather_allowlist` is ignored by two block-eligible checks.**
`checks/at_import_census.py` and `checks/module_doc_budget.py` never consult
`policy.qa.grandfather_allowlist` (verified by grep — no reference exists in
either file), while the other block-eligible checks all honour it.
`config/models.py:854`-area documents the option as "held to advise-only
forever (R12)". In block mode, a grandfathered file can be **denied** by these
two checks — a direct R12 contract violation. Harmless under the warn
defaults, but the option's promise is false as shipped. *Fix*: downgrade to
ADVISE on allowlist match in both (the `_matches_allowlist` helper already
exists five times over — see F5).

**F3 — Real-client scaling: no vendored-dependency exclusion inside the
configured trees, and an unpruned whole-repo walk every session start.**
Two halves, same class as the Task 3.6 vendored-daemon fix but unfinished for
the generic case:

- `corpus.py:144-162` (`_is_excluded`) knows only CHANGELOG, RELEASES/,
  worktrees, the vendored daemon install, and the plan archive. `iter_corpus_paths`
  then rglobs the whole of `trees.human` — default `docs/`. A client whose
  `docs/` is a Docusaurus/site root (`docs/node_modules/`, `docs/build/`,
  `docs/.docusaurus/`) gets every package README indexed, hashed, and
  dead-link-scanned: a multi-second-to-minutes first corpus build plus a
  permanent advisory wall.
- `checks/module_doc_budget.py:190` does `project_root.rglob("CLAUDE.md")` on
  **every sweep** (every new session). Its `_EXCLUDED_DIR_NAMES` post-filter
  (`node_modules`, `vendor`, `untracked`, `.git`, `worktrees`) does not prune
  the traversal — `Path.rglob` still physically descends a 500k-file
  `node_modules` and `.git` each session start. The set also omits `dist`,
  `build`, `target`, `.venv`, `.next`, `third_party`.

Client-mode verification used a small dummy fixture, which cannot see this.
Since the manifest promotes enabling to every upgrading client, this is the
single most likely "enabled it, regretted it" path. *Fix*: add the common
vendored/build dir names to `_is_excluded`, and replace the budget check's
rglob with a pruned `os.walk` (or have it iterate the already-built corpus).

**F4 — The system is undocumented in the reference docs.**
`docs/guides/HANDLER_REFERENCE.md` — which root `CLAUDE.md` names as "the full
per-handler options reference", and which documents the plan_qa trio in depth
(e.g. `plan_qa_edit` at line 1773) — contains **zero** mention of
`docs_qa_edit`, `docs_qa_commit_gate`, `docs_qa_sweep`, or the top-level
`documentation:` block. In fact no file anywhere under `docs/` mentions
docs-qa at all. A client enabling a promoted feature has no human-tree
reference for its options — and an SSoT-enforcement system whose own options
have no documented home is a poor advertisement for itself. *Fix*: add the
three handler sections (plan_qa precedent) plus the `documentation.qa` policy
block to HANDLER_REFERENCE.md.

### 3b. Nits and follow-ups (not release-blocking)

**N1 — Shipped skill contradicts the shipped agent about report output.**
`skills/docs-qa/SKILL.md:34` says the agent reports to
`untracked/reports/YYYY-MM-DD-docs-qa-<topic>.md`; the agent template's Output
section (`install/templates/agents/hooks-daemon-docs-qa.md:196-202`) says
inline-only unless the caller names a target. A conflicting truth shipped
inside the conflicting-truth detector — cheap, worth fixing alongside F1–F4.

**N2 — Structural block-eligibility is convention, not structure.**
`docs_qa/types.py` declares `file_exists_before` but no check reads it; the
worse-only/new-only discrimination rests entirely on whether the calling
surface remembered to populate `file_content_before` — F1 is exactly that
failure already happening in-tree. Have worse-only checks branch on the
explicit field and fail fast when it is absent at EDIT stage.

**N3 — ~90 lines of git-commit-command parsing duplicated verbatim** between
`docs_qa_commit_gate.py:35-126,188` and `plan_qa_commit_gate.py:36-140,209`
(one comment even says "see plan_qa_commit_gate's identical table"). Extract a
shared `utils/git_commit_command.py`. Related copy-paste: `_matches_allowlist`
×5 across checks, `_is_rules_file` ×2, the `docs-qa/index.json` cache path
spelled out ×4, and mode tokens (`"block"`/`"advise"`) re-declared per surface
instead of one enum.

**N4 — Dead code**: `CheckContext.commit_message` (populated by ~20 lines of
parsing, read by nothing), `CheckContext.file_exists_before` (see N2), and two
test-only extractors in `structured_blocks.py` (:160, :173). Also stale
docstrings: `docs_qa/__init__.py:6` and `report.py:5-8` still describe the
surfaces as future work.

**N5 — Robustness/correctness smalls**: unguarded `read_text` in five sweep
checks (an undecodable or permission-denied file matching a manifest glob
aborts the entire SessionStart dispatch — `corpus.py` guards
`UnicodeDecodeError` but the checks re-reading files do not); corpus cache
written via a fixed `index.json.tmp` name so concurrent CLI + handler sweeps
can race (`corpus.py:402-404` — use `tempfile.mkstemp`);
`plan_promotion_disposition` fires on every later commit touching an
already-terminal PLAN.md rather than only on the flip (never compares HEAD,
though `gitfacts.head_file_text` is available and `rules_file_orphan_shrink`
does exactly that); three divergent spellings of the `ssot-quote` marker
regex (`quotes.py:66`, `structured_blocks.py:68`, `module_doc_budget.py:66`)
so a `<!--ssot-quote:…-->` with no spaces is treated differently by each
consumer; `pointer-resolves` at EDIT stage gates on `is_in_scope` while the
handler matches on the wider `is_lintable_path`, so a new dead link in e.g.
`src/CLAUDE.md` is silently unchecked despite the handler guidance claiming
otherwise.

**N6 — Self-observations on the dogfood state** (accepted behaviour, worth
knowing): `.claude/HOOKS-DAEMON.md` does not list the three new handlers — its
version marker (v3.56.0) matches the daemon so `generated-doc-hand-edit`
correctly stays silent (content freshness is explicitly out of its scope), and
the release process's Step 3 regeneration will heal it, but until then the
tracked generated doc contradicts the live config. The 16 residual
pointer-resolves advisories are all under the grandfathered `CLAUDE/UPGRADES/**`
and the 8 at-import-census hits are root `CLAUDE.md`'s deliberate resident
imports — both will occupy sweep-advisory slots every session forever; the
latter could be silenced honestly by extending `resident_at_imports` with the
eight targets (they ARE deliberately always-loaded, which is precisely what
the option exists for — the current config leaves R6's "deliberate resident
set in root CLAUDE.md" flagged by the very check implementing R6).
`CLAUDE/DocumentationStrategy.md:5,167` still cites the plan at its
pre-archive path and its "Enforcement status" closer still reads "Until those
ship…" — both now stale on the canonical doc itself (R11 optics; backtick
spans, so pointer-resolves cannot see them).

## 4. Does what was done make sense?

**Yes — the design is the right one, and the discipline behind it shows.**
The core judgements all hold up under adversarial reading:

- **The deterministic/semantic split (R13) is the load-bearing decision and it
  is correct.** Everything mechanically checkable (dead links, quote drift,
  budgets, manifests, exact duplicate blocks) is deterministic and
  block-capable-by-ratchet; everything requiring judgement (paraphrase drift,
  conflicting truths) went to a read-only reporting agent. The hard-coded
  advisory-only stance on `duplicate-block`, backed by the hand-triage
  (11 shared blocks across 198 docs), is exactly the Plans 00208/00214
  measurement discipline the plan promised.
- **Warn-first, off-by-default, per-check ratchet** matches the project's own
  history of what gets handlers disabled. The block-eligibility tiering
  (worse-only) mirrors `plan-doc-size`, which has proven livable.
- **Dogfooding was real, not ceremonial**: 168 → 34 findings with every fix
  committed, four field-found defects (3.4/3.5/3.6/3.1h) each root-caused and
  regression-tested, a genuine agent dispatch producing an audit that drove
  the migration, and Plan 00286 shipped to close a gap the closure itself
  exposed. The 34 residual advisories are all explainable and deliberate.
- **The ssot-quote mechanism** is the most novel piece and its shape is sound
  (tracked verbatim quotation beats both blanket duplication bans and
  allowlists); its edit-time + sweep re-verification split is correctly
  reasoned.
- The plan's paperwork is exemplary: decisions recorded with provenance,
  journal dispositions per R8, index rows and statistics consistent.

The defects found are the residue of speed, not of wrong thinking: a missing
argument at one call site (F1), an allowlist two checks forgot (F2), an
exclusion generalisation not carried to its conclusion (F3), and a reference
doc not yet written (F4). The one genuinely structural criticism is N2 — the
system's most important invariant (worse-only blocking) is enforced by every
caller remembering a kwarg rather than by the type system, and F1 is the
proof that this will be forgotten again. That is worth a deliberate fix, not
just a patch.

**Release recommendation**: land F1–F4 (plus the one-line N1) before tagging
v3.57.0, or ship with the manifest's two docs-qa promotions downgraded to
`recommended: false` and promote in the following release once they land.
