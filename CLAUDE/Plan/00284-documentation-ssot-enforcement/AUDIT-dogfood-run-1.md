# Docs-QA Dogfood Audit — Run 1 (first real dispatch of `hooks-daemon-docs-qa`)

> Provenance: produced by the shipped `hooks-daemon-docs-qa` agent's first genuine
> dispatch against this repository (Task 3.1g acceptance + Task 3.2 worklist seed).
> Delivered inline by the audit agent; persisted here verbatim. Scope: 110 tracked
> markdown files; 13 topics deep-read; 33 source comment blocks adjudicated;
> judged against `CLAUDE/DocumentationStrategy.md` (R1–R13).

## Part 1 — NEW findings (not previously in Task 3.2)

### N1: The venv layout is stated four incompatible ways, twice inside a single file

**Class**: conflicting-truth · **Severity**: conflict (highest in this report)

- `CLAUDE/LLM-INSTALL.md:57` — "Creates isolated venv at `.claude/hooks-daemon/untracked/venv/`"
- `CLAUDE/LLM-INSTALL.md:88-92` — "**Never hand-build the venv.** … `venv-{slug}-py{MM}-{fingerprint}/` … A hand-made `untracked/venv/` is the retired pre-v3.7.0 layout and `resolve_venv.sh` refuses it, so every wrapper call then exits 5."
- `CLAUDE/Worktree.md:92-96` — "**Why not `python3 -m venv untracked/venv`**: that builds the retired pre-v3.7.0 layout."
- `CLAUDE/Worktree.md:773` — "3. Creates Python venv at `untracked/venv/`"
- `CLAUDE/AgentTeam.md:176, 301, 1375, 1482` — instructs `python3 -m venv untracked/venv` and points at `/workspace/untracked/venv/`
- `src/claude_code_hooks_daemon/skills/hooks-daemon/install.md:27` — "**Creates isolated venv** at `.claude/hooks-daemon/untracked/venv/`"
- `CLAUDE/SELF_INSTALL.md:23` and `CLAUDE/LLM-UPDATE.md:3` — `untracked/venv-py{MM}-{fingerprint}/`, missing the `{slug}` component

Four distinct spellings coexist: the retired `untracked/venv/`, the v3.7.0
`venv-py{MM}-{fp}/`, the current v3.19.1 `venv-{slug}-py{MM}-{fp}/`, and the
self-install `/workspace/untracked/` variant. Two files contradict *themselves*
thirty lines apart.

**Evidence**: `src/claude_code_hooks_daemon/daemon/paths.py:200` composes the
directory name as `project_path_slug(root)` + python fingerprint, so the
slug-bearing form is the only correct one. The *warning* paragraphs in
`LLM-INSTALL.md` and `Worktree.md` were added recently while the instructional
lines around them were never revisited — migrated-forward truth sitting beside
un-migrated truth in one file.

**Recommended remediation**: This is a derived fact (R5) whose real source is
`daemon/paths.py`. Give it one documented canonical home — the natural fit is a
"Venv layout" section in `CLAUDE/SELF_INSTALL.md` (already the deepest
treatment) — corrected to the slug-bearing form. Then **point** from
`LLM-INSTALL.md`, `LLM-UPDATE.md`, `Worktree.md`, `AgentTeam.md`,
`CLIENT-MODE-TESTING.md`, `scripts/install/README.md` and
`skills/hooks-daemon/install.md`, and **delete** every instruction to hand-build
`untracked/venv/`, which is not merely stale but actively breaks the wrapper
(exit 5).

### N2: 68 `@`-imports outside the resident allowlist, including a mutual import cycle

**Class**: scattered-truth-no-home (R6 breach) · **Severity**: conflict-adjacent —
measurable per-session token cost

`.claude/hooks-daemon.yaml:910` sets `resident_at_imports: ["CLAUDE.md"]`, so
only root `CLAUDE.md` may use `@`. Every other `@`-import in the corpus violates
R6. There are 68 of them (76 sweep findings minus the 8 grandfathered root
ones). The damaging shape is a cycle rooted in files root `CLAUDE.md` already
imports:

- `CLAUDE/CodeLifecycle/General.md` imports `@CLAUDE/CodeLifecycle/General.md` five times (itself), `@…/Features.md` four times, `@…/Bugs.md` three times
- `CLAUDE/CodeLifecycle/Features.md` imports `@…/Bugs.md`, `@…/General.md`, `@CLAUDE/PlanWorkflow.md` (x2), `@CLAUDE/PROJECT_HANDLERS.md`, `@CLAUDE/AcceptanceTests/GENERATING.md`, `@CLAUDE/development/CLIENT-MODE-TESTING.md`
- `CLAUDE/AgentTeam.md` imports `@CLAUDE/Worktree.md` six times; `CLAUDE/Worktree.md` imports `@CLAUDE/AgentTeam.md` back

**Evidence**: root `CLAUDE.md` imports
`@CLAUDE/CodeLifecycle/{Features,Bugs,General}.md`. `@`-imports resolve
recursively, so `PlanWorkflow.md`, `PROJECT_HANDLERS.md`,
`AcceptanceTests/GENERATING.md` and `CLIENT-MODE-TESTING.md` are all eagerly
inlined into every session even though root `CLAUDE.md` never asks for them —
exactly the progressive-disclosure defeat R6 names.

**Recommended remediation**: Convert all 68 to plain markdown links. No content
moves; one-character-class edit per site. Prioritise the CodeLifecycle cluster
and `AgentTeam.md`/`Worktree.md`, which are the ones actually inlining today.

### N3: The priority-range table lives in 12 places and three of them are wrong

**Class**: scattered-truth-no-home, with two embedded conflicting-truths ·
**Severity**: conflict

Copies: `CLAUDE.md:632-638`, `CLAUDE/ARCHITECTURE.md:287-299` and `:543-550`,
`CLAUDE/HANDLER_DEVELOPMENT.md:463-470`, `CLAUDE/Code/HooksSystem.md:598`,
`CLAUDE/LLM-INSTALL.md:620-622`, `CLAUDE/PlanWorkflow.md:572`,
`CLAUDE/development/QA.md:493-495`, `CLAUDE/development/RELEASING.md:426`,
`docs/guides/CONFIGURATION.md:187-194`,
`docs/guides/HANDLER_REFERENCE.md:3092-3094`, `CONTRIBUTING.md:221-223`,
`src/claude_code_hooks_daemon/skills/hooks-daemon/dev-handlers.md:184-186`.

Three are factually wrong:

- `docs/guides/CONFIGURATION.md:190` — "`curl_pipe_shell` (15)". The code says `CURL_PIPE_SHELL = 10` (`src/claude_code_hooks_daemon/constants/priority.py:47`); this repo's own live config runs it at 16. The doc matches neither.
- `CLAUDE/ARCHITECTURE.md:544` — "0-9: Test handlers (hello world, architecture enforcement)". Those handlers do not exist; `priority.py:35-39` says so explicitly in its own comment, and root `CLAUDE.md:632` says "no built-in handlers ship here".
- `CLAUDE/HANDLER_DEVELOPMENT.md:470` — "100+ | Logging | Notification logger, session cleanup". Root `CLAUDE.md:638` says the 100+ range is reserved with nothing shipping in it.

The copies also disagree on the advisory band: root `CLAUDE.md` says 56-65,
every other copy says 56-60. The live registry has handlers at 61, 62 and 63, so
56-65 is the accurate one and the other eleven copies are all wrong together.

**Recommended remediation**: Canonical home is
`src/claude_code_hooks_daemon/constants/priority.py` (R5 — a derived fact with a
generator). Nominate `CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide` as the
single documented statement, correct it to 56-65 and drop the phantom examples,
then replace the other eleven with a pointer or an `ssot-quote` block (R4b) so
the checker catches the next drift. The examples column should name real
handlers or be removed — it is the part that rots.

### N4: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` carry five identical untracked blocks, including two client-facing templates

**Class**: paraphrase-duplicate (exact, in fact) · **Severity**: duplicate —
high, because these are templates users paste

| Block                                                 | INSTALL    | UPDATE       |
| ----------------------------------------------------- | ---------- | ------------ |
| 20-line `### Hooks Daemon` CLAUDE.md section template | `:356-375` | `:434-453`   |
| 14-line `hooks-daemon.yaml` header template           | `:387-400` | `:467-480`   |
| `grep -n "### Hooks Daemon" CLAUDE.md` verification   | `:348-350` | `:426-428`   |
| `grep -q "AFTER EDITING THIS FILE"` verification      | `:381-383` | `:461-463`   |
| `debug_info.py /tmp/debug_report.md`                  | `:541-543` | `:1138-1140` |

**Evidence**: byte-identical after whitespace normalisation; no `ssot-quote`
markers on either side.

**Recommended remediation**: The two templates are the ones that matter — they
are what a client's `CLAUDE.md` and config header end up containing, so drift
ships broken instructions to users. Make `LLM-INSTALL.md` canonical for both and
have `LLM-UPDATE.md` carry `ssot-quote` blocks (R4b) rather than plain links —
the reader genuinely needs the text inline at that point of use. The three short
verification snippets are the textbook R4b case too.

### N5: A hand-written mirror of `core.utils`'s API in two agent-tree docs

**Class**: paraphrase-duplicate · **Severity**: duplicate

- `CLAUDE/Code/HooksSystem.md:637-643`
- `CLAUDE/PROJECT_HANDLERS.md:341-347`

Both carry the same `from claude_code_hooks_daemon.core.utils import (...)`
block with the same trailing comments naming what each helper extracts.

**Evidence**: identical after normalisation. R7d explicitly disqualifies
"hand-written API mirrors of the module's own code"; the canonical home is
`core/utils.py`'s own docstrings.

**Recommended remediation**: Keep one copy (`PROJECT_HANDLERS.md` is the more
natural home — the guide someone follows while writing a handler) and have
`HooksSystem.md` point at it.

### N6: `CLAUDE/development/CLAUDE.md` contradicts the canonical audience split and indexes 2 of its 5 files

**Class**: conflicting-truth · **Severity**: conflict

- `CLAUDE/development/CLAUDE.md:9-11` — "**User Documentation**: `/CLAUDE/` root level … How to use the daemon"
- `CLAUDE/DocumentationStrategy.md:14-15` — "**Agent tree** (`CLAUDE/`) | agents" and "**Human tree** (`docs/`) | humans"

The sub-doc relabels the agent tree as the user/human tree — the exact axis R3
exists to fix, in the doc a contributor reads to decide where a new file goes.

Separately, `:26-28` lists "Files in This Directory: RELEASING.md, QA.md" — the
directory holds five files (`LESSONS.md`, `DOC-CONVENTIONS.md`,
`CLIENT-MODE-TESTING.md` missing). R7d: prose indexes rot fastest; this one has.

**Recommended remediation**: Rewrite to a \<=15-line routing table (R7d), fix the
audience labels to point at `CLAUDE/DocumentationStrategy.md`, delete the prose
file index rather than extending it.

### N7: Two satellite charters restate the SSoT rule without citing its canonical home

**Class**: paraphrase-duplicate of normative content · **Severity**: duplicate

- `docs/CLAUDE.md:1-3` — restates "Single Source of Truth: Every piece of information lives in exactly one canonical file."
- `.claude/skills/CLAUDE.md:1-3` — restates "Skills must not duplicate content from other canonical sources"

Both state R1 in their own words; neither links
`CLAUDE/DocumentationStrategy.md`. R11 requires this policy to obey itself.
`.claude/agents/CLAUDE.md` *does* cite it — the correct shape already exists one
directory over; these two predate it.

**Recommended remediation**: Replace the restated rule with a one-line pointer
to `CLAUDE/DocumentationStrategy.md`. Keep the per-file canonical-source tables
in both — legitimate R7d routing tables.

### N8: Three dead pointers with the same cause, plus one wrong relative depth

**Class**: adjudicated-mechanical-hit (`pointer-resolves`) · **Severity**:
duplicate-tier (cheap, mechanical)

- `CLAUDE/Plan/README.md:1247` → `00213-planlib-plan-folder-orchestrator-tooling/PLAN.md`; folder is under `Completed/` (line 295 of the same file links it correctly)
- `CLAUDE/Performance/README.md:79` → `../Plan/00156-…/PLAN.md`; actual path is under `Completed/`
- `.claude/skills/configure/SKILL.md:104` → `../../docs/guides/HANDLER_REFERENCE.md` resolves to `.claude/docs/guides/…`; needs one more `../`

**Recommended remediation**: Insert `Completed/` in the two plan links; correct
the relative depth in the skill. All three are "plan archived, backlink not
updated" — worth a note in R8's promotion checklist, since archiving a plan
predictably orphans inbound links.

### N9: Files instruct the denied `run_all.sh` outside the human-facing exception

**Class**: conflicting-truth · **Severity**: duplicate-tier

`CLAUDE/QA.md:34` establishes the rule: `enforce_llm_qa` denies a direct
`run_all.sh` invocation by an agent. Remaining agent-reachable sites:

- `BUG_REPORTING.md:209` — reached from `CLAUDE/CLAUDE.md`'s troubleshooting route, so an agent following that path hits a denied command
- `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md:52` — archived, dated record under R8/R12 — **leave alone** (listed only so a re-run does not re-litigate)

`CONTRIBUTING.md:52,274` and `README.md:508` are human-facing by charter —
correct, not reported.

**Recommended remediation**: `BUG_REPORTING.md` → point at
`./scripts/qa/llm_qa.py all` with the human variant as an aside, matching
`CLAUDE/CodeLifecycle/README.md:76`'s already-correct wording.

## Part 2 — Confirmations of the tracked Task 3.2 backlog

All verified against current `main`; all still real, none newly blocking.

| Task 3.2 item                                                   | Status                             | Evidence added by this run                                                                                                                                                                       |
| --------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CLAUDE/AgentTeam.md` run_all.sh sites + stale counts           | Confirmed                          | 16 instructive sites (`:77, 217, 317, 397, 689, 765, 1115, 1134, 1195, 1348, 1445, 1505, 1553, 1648, 1654, 1679, 1782, 1806`); stale "all 7 checks" count at `:397` and `:1806`                  |
| `CLAUDE/Worktree.md` run_all.sh sites                           | Confirmed                          | 14 sites (`:9, 373, 427, 455, 575, 588, 659, 691, 794, 801, 1018, 1032, 1053, 1220, 1239`)                                                                                                       |
| `CLAUDE/PlanWorkflow.md` 3-digit plan numbering                 | Confirmed, narrower than described | Only `:886` (`Refs: CLAUDE/Plan/001-handler-implementation`) plus `XXX`/`001-`/`002-` template placeholders; prose elsewhere already 5-digit                                                     |
| `CLAUDE/CLAUDE.md` prose index → routing table                  | Confirmed, worse than recorded     | `:57-62` labels `development/QA.md` "QA pipeline and automation" but that file is *QA Patterns & Solutions*; the actual pipeline doc `CLAUDE/QA.md` is not indexed at all — the index misdirects |
| `.claude/rules/ccy-supervisor-dogfooding.md` fails pointer-only | Confirmed                          | 46-line body (budget 15) + forbidden fenced block. Promotion target `.claude/ccy/CLAUDE.md` does not exist yet — create the home first, per R7a                                                  |
| `.claude/rules/importing-reports.md` fails pointer-only         | Confirmed                          | 57-line body + forbidden 10-row table; its `:45-55` section is near-verbatim with root `CLAUDE.md`'s Report Handling — thin against that section                                                 |
| release SKILL.md step numberings                                | Not re-derived                     | Belongs to skill thinning, out of this pass's scope                                                                                                                                              |

`AgentTeam.md`/`Worktree.md` also account for the grandfathered
`module-doc-budget` and one `duplicate-block` finding, confirmed and not
re-itemised.

## Part 3 — Adjudicated as fine (so the next run does not re-litigate)

| Candidate                                                                                                   | Verdict                                                                                                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE/QA.md` vs `CLAUDE/development/QA.md`                                                                | Not a duplicate — pipeline vs failure-mode cookbook; legitimate separation (the *index entry* describing them is wrong — that is N6/Task 3.2)                                                                                   |
| `docs/QA.md` vs `CLAUDE/QA.md`                                                                              | Compliant R3 pair — terse human prose pointing into the agent tree                                                                                                                                                              |
| `CLAUDE/development/DOC-CONVENTIONS.md` vs `DocumentationStrategy.md`                                       | Not overlapping — mechanical conventions vs SSoT structure                                                                                                                                                                      |
| CodeLifecycle trio's shared "Definition of Done" shape                                                      | Not a duplicate — different checks per change class; only the heading recurs                                                                                                                                                    |
| `.claude/agents/release-agent.md:487` vs `BREAKING-CHANGES-TEMPLATE.md:95`                                  | False positive — a single one-line example link                                                                                                                                                                                 |
| `GENERATING.md:178-180` vs `PLAYBOOK-v1-manual-archived.md:131-133`                                         | Archive — dated record (R8 historical); leave it                                                                                                                                                                                |
| `CLAUDE/Plan/00100/PLAN-v1.md` vs `PLAN.md`                                                                 | Out of scope — superseded draft inside a completed plan folder                                                                                                                                                                  |
| `CLAUDE/CodeLifecycle/General.md:98-106` vs `CLAUDE/QA.md:62-70`                                            | Borderline/low — deliberately edited in lockstep; an `ssot-quote` would cost nothing and make the next divergence visible                                                                                                       |
| 29 of 33 source comment blocks                                                                              | R7e-compliant rationale — each keyed to a failure mode or plan number, local to its file (e.g. `daemon/paths.py:203-219`, `constants/permissions.py:25`, `core/hook_result.py:84`, `utils/secret_file_matching.py:300/431/459`) |
| `install/templates/mkplan.bash:1-50` header                                                                 | Fine — self-describing implementation notes                                                                                                                                                                                     |
| Identical 21-line SELF-BOOTSTRAP comment in `daemon-cli.sh:22`, `health-check.sh:16`, `init-handlers.sh:16` | Fine as documentation — rationale, not a restated doc fact; the triplication is a *code* sharing question                                                                                                                       |
| 54 of 61 `module-doc-budget` findings                                                                       | Scanner artefact — copies of 9 tracked files inside `.claude/worktrees/agent-*/` checkouts (see tooling follow-up T2)                                                                                                           |

## Verdict on the deterministic pre-seed

The two instruments were complementary rather than overlapping — R13 working as
designed — but the sweep's signal-to-noise is currently poor and its
highest-value class was one the agent alone could find. Of 168 sweep findings,
54 were worktree copies and 76 were `at-import-census`; the top semantic
findings (N1's four-way venv contradiction, N3's wrong priority numbers, N6's
inverted audience labels) produced **zero** deterministic findings — they are
incompatible claims in different words, precisely the remainder R13 assigns to
the agent. Conversely, N2 (68 `@`-imports incl. a self-importing file) would not
have been enumerated reliably by reading, and the sweep handed it over complete.
`duplicate-block` earned its keep on N4/N5 but produced three false positives
out of eight — about the rate you would want to see before promoting it past
advisory. `find-comment-blocks` was the weakest performer: 33 candidates, 0
findings — the codebase's comment discipline is genuinely good, so the finder
confirmed a negative.

## Tooling / agent-definition follow-ups (from the run's self-critique)

- **T1**: `duplicate-block` findings carry no line numbers — should report `path:start-end` for BOTH sides; without it the check is not actionable.
- **T2**: The sweep scans `.claude/worktrees/` — 54/61 `module-doc-budget` findings were transient agent-worktree copies; sweep counts vary with how many agents are running. Corpus indexer should exclude worktree roots.
- **T3**: The agent definition instructs writing a report file to `untracked/reports/`, which conflicts with harness no-file-report instructions — drop the file-writing instruction or have the caller pass the target explicitly.
- **T4**: The agent definition lacks the historical/archive boundary guidance — cite `CLAUDE/PlanWorkflow.md`'s "Truth is enforced on LIVE plans, never on the historical record" section by name, or a careless run files dead-link findings against frozen v2 upgrade guides.
- **T5**: Freshness tiebreaker: recommend `git log -L <range>` for intra-file conflicts (file-level `git log -1` says nothing when both statements share a file).
- **T6**: Define the shipped-vs-deployed boundary: `src/.../skills/` and `install/templates/` are canonical sources; their `.claude/` deployed counterparts are generated copies — record them in the generated-docs manifest or the next run files them as duplicates (e.g. the two `docs-qa/SKILL.md` copies).
