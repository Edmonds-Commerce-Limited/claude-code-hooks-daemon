# Release code review — strategies/, plan_qa/, docs_qa/ (v3.64.0..HEAD)

Scope: `git diff v3.64.0..HEAD -- src/claude_code_hooks_daemon/strategies/
src/claude_code_hooks_daemon/plan_qa/ src/claude_code_hooks_daemon/docs_qa/`
— 39 files, +861/−149. Reviewer: Opus 5.

Evidence runs (all from `/workspace`):

- `./scripts/test.bash tests/unit/plan_qa tests/unit/docs_qa tests/unit/strategies -q`
  → **2897 passed**, exit 0.
- `bin/hooks-daemon plan-qa --sweep` → `0 findings — plan tree is clean`.
- `bin/hooks-daemon docs-qa --sweep` → 9 findings (0 block, 9 advise), all
  `pointer-resolves` relocations. Captured at
  `untracked/scratch/docs-qa-sweep.txt`.

Every finding below was reproduced against the shipped code; reproduction
one-liners are inline.

---

## DEFECTS

### D1 — `release-blocked-plan` blocks any owner-gated item, with a wrong diagnosis

**File:** `src/claude_code_hooks_daemon/plan_qa/checks/release_blocked_plan.py`,
the `|blocked on human` alternative inside `_WAITS_ON_RELEASE_RE` (the regex
block beginning at the `_WAITS_ON_RELEASE_RE` definition).

**Scenario (inputs → wrong outcome).** A live plan carries an owner-gated
criterion that has nothing to do with a release:

    - [ ] **BLOCKED ON HUMAN** — the owner must choose between tier A and tier B.

Writing that PLAN.md is DENIED at the edit gate with:

    block | CLAUDE/Plan/00421-example/PLAN.md: an unticked item waits on a RELEASE
            — - [ ] **BLOCKED ON HUMAN** — the owner must choose between tier A and tier B.

and a remediation instructing the author to stage a release-bound consequence
into `CLAUDE/UPGRADES/UNRELEASED/`, which is not the fix for an owner gate.

Reproduction:

    .venv/bin/python -c "
    from pathlib import Path; import tempfile
    from claude_code_hooks_daemon.plan_qa.checks.release_blocked_plan import CHECKS
    from claude_code_hooks_daemon.plan_qa.types import CheckContext
    body='- [ ] **BLOCKED ON HUMAN** — the owner must choose between tier A and tier B.'
    content=f'# Plan 00421: example\n\n**Status**: In Progress\n\n## Success Criteria\n\n{body}\n'
    with tempfile.TemporaryDirectory() as d:
        root=Path(d); p=root/'CLAUDE/Plan/00421-example/PLAN.md'
        p.parent.mkdir(parents=True); p.write_text(content)
        ctx=CheckContext(project_root=root, plan_dir_rel='CLAUDE/Plan',
                         file_path=p, file_content=content, file_exists_before=True)
        print([(f.level, f.message) for f in CHECKS.edit.run(ctx)])
    "

The same regex also matches `BLOCKED ON HUMAN: waiting for a ruling on the
priority table.` and `Ask the owner; blocked on human input until they reply.`

**Why this is a defect, not a preference.** The module's own docstring states
the contract the regex does not keep: *"High precision by design: each phrase
names a release EVENT the item depends on"*. `blocked on human` names no
release. It is also redundant — the motivating line from Plan 00409 ("BLOCKED
ON HUMAN — a published version carries the fix") already matches via
`published version carries`, so the parametrised test at
`tests/unit/plan_qa/checks/test_release_blocked_plan.py` still passes with the
alternative removed. Owner-gated items are a first-class shape in this project
(`STOPPING BECAUSE: [awaiting-human]`, the whole 00412/00416/00419 owner-ruling
workflow), so this will fire, and it fires at BLOCK on the edit surface.

No live plan in the tree matches today (`plan-qa --sweep` is clean), so this is
latent rather than active.

**Fix.** Delete the `|blocked on human` alternative. If a bare "blocked on
human" is wanted as a signal, require it to co-occur with a release token
(e.g. `blocked on human.*release`), and add a negative test for
`- [ ] BLOCKED ON HUMAN: the owner must rule on X.`

---

### D2 — `quote-source-stale` raises instead of reporting when a path or anchor contains a brace

**File:** `src/claude_code_hooks_daemon/docs_qa/checks/quote_source_stale.py`,
the `message=` argument inside `_finding` (lines 41-45).

The reformat moved `.format()` from a constant substring onto the **whole
f-string**:

    # before
    f"`{rel_path}#{anchor}` changed, and {quoter_list} " "quote{} it.".format(...)
    # after
    f"`{rel_path}#{anchor}` changed, and {quoter_list} quote{{}} it.".format(...)

**Scenario.** Any `{`/`}` in `rel_path`, `anchor`, or a quoter path becomes a
live format placeholder after interpolation:

    .venv/bin/python -c "
    from claude_code_hooks_daemon.docs_qa.checks.quote_source_stale import _finding
    _finding('CLAUDE/Doc{x}.md','anchor-{1}',('a.md','b.md'))
    "
    # KeyError: 'x'

`_ANCHOR_MARKER_RE` in `docs_qa/quotes.py:65` captures `(\S+)`, so a braced
anchor (`handler.{name}`) is accepted by the quote mechanism and then crashes
this check. `docs_qa/runner.py:26-29` has no per-check exception guard, so the
exception propagates out of the **entire EDIT stage** — every other docs-QA
check's findings for that edit are lost. The module docstring claims the
opposite: *"degrades to silence, never to a false positive or a crash"*.

**Fix.** Do not format an interpolated string:

    plural = "s" if len(quoters) == 1 else ""
    message = f"`{rel_path}#{anchor}` changed, and {quoter_list} quote{plural} it."

Add a regression test with a braced anchor. This file's change ships with no
test change at all — see the checklist below.

---

### D3 — `PlanTree.scan` weakened `is_file()`/`is_dir()` to `exists()`, opening the structural gate

**File:** `src/claude_code_hooks_daemon/plan_qa/model.py:498-502`.

    has_readme=authored_path_exists(root, README_FILENAME),          # was (root / README).is_file()
    has_completed_dir=authored_path_exists(root, completed_dir),     # was (root / completed).is_dir()
    has_cancelled_dir=... authored_path_exists(root, cancelled_dir)  # was .is_dir()

`authored_path_exists` is `Path(normpath(...)).exists()`
(`utils/authored_paths.py:143`) — it answers "something is there", not "a file"
or "a directory".

**Scenario.** A plan tree in which `README.md` is a directory and `Completed`
is a regular file:

    .venv/bin/python -c "
    from pathlib import Path; import tempfile
    from claude_code_hooks_daemon.plan_qa.model import PlanTree
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)/'Plan'; root.mkdir()
        (root/'README.md').mkdir(); (root/'Completed').write_text('x')
        t=PlanTree.scan(root)
        print(t.has_readme, t.has_completed_dir, [p.name for p in t.stray_files])
    "
    # True True ['Completed']

Consequences:

1. `structure-archive-dirs` (`plan_qa/checks/structure_archive_dirs.py:47,58`,
   both **BLOCK**) does not fire, although its own comment says the no-README
   case is *"not a state to wave through"* precisely because
   `context.readme` is then None and half the check suite silently no-ops.
2. `plan_qa/context.py:145` still gates parsing on `readme_path.is_file()`, so
   `has_readme=True` and `context.readme=None` coexist — two facts derived from
   the same file now disagree.
3. `scan()` contradicts itself in one call: `Completed` is reported as a stray
   file *and* as the archive directory existing.

Reachability is low (nobody creates a file named `Completed`), and I have not
inflated the severity for that reason — but it is a fail-open in a BLOCK gate,
not a style point, and the fix is one line per field.

**Fix.** Use the idiom already present 20 lines below at `model.py:522`
(`plan_md = authored_path(path, PLAN_DOC_FILENAME); plan_md.is_file()`):

    has_readme=authored_path(root, README_FILENAME).is_file(),
    has_completed_dir=authored_path(root, completed_dir).is_dir(),

This still satisfies `scripts/qa/check_authored_path_stat.py` (the predicate is
applied to the helper's result, not to a raw join). Add the two-case test to
`tests/unit/plan_qa/test_model.py`, which this bundle did not touch.

---

## NON-DEFECTS

### N1 — `pointer-resolves` emits one finding per link *occurrence*, not per distinct link

`docs_qa/checks/pointer_resolves.py` `_run_sweep` appends without
deduplication. The real sweep shows the cost: `CLAUDE/Plan/00422-.../NIGGLES.md`
produces **five identical two-line findings** for one repeated target
(`untracked/scratch/docs-qa-sweep.txt`). The plan-QA twin already dedupes
(`plan_link_resolves.py`, the `if link in moved: continue` guard). Fix: key
findings on `(rel_path, target)` in `_run_sweep`/`_run_staged`/`_run_edit`.

### N2 — Relocation messages assert "archived" for links that were merely written wrongly

`plan_link_resolves.py` and `pointer_resolves._relocation` both say "have been
archived" / "the plan was archived, not deleted" for **any** target that
resolves by plan number. A live sibling plan linked by a wrong or root-relative
path produces:

    advise | PLAN.md links to plan(s) that have been archived: CLAUDE/Plan/00002-second/PLAN.md
       -> Repoint: ... The plan was archived, not deleted — ...

while plan 00002 is sitting in the active root. The suggested repoint is
correct; only the explanation is false. Fix: word it "has moved / is not at the
path written", and mention archival only when `relocated.rel_path` is under an
archive directory (`PlanTreeLayout.is_archived` already answers that).

### N3 — plan QA and docs QA disagree about repo-root-relative links

`pointer_resolves._resolves` falls back to "relative to the repo root" and
treats such a link as resolving; `plan_link_resolves._resolves_literally` has no
such fallback. The same link in the same PLAN.md therefore passes docs QA and is
reported by plan QA (`PLAN.md link target(s) do not exist:
CLAUDE/ARCHITECTURE.md` — reproduced in a temp tree). Strictly, plan QA's answer
matches what GitHub renders, so the leniency is arguably the older bug; either
way the two subsystems should not answer one question two ways. Decide which is
canonical and share the resolver.

### N4 — `_is_skippable` duplicated between the two link checks, already divergent

`plan_link_resolves._is_skippable` mirrors `pointer_resolves._is_skippable`, but
tests external URLs as `"://" in target` where the original uses an anchored
scheme regex, and re-declares `_PLACEHOLDER_TOKENS`. This is the exact failure
mode `utils/markdown_links.py` was created to prevent for the link regex. Fix:
move `_is_skippable` and the placeholder tokens next to `extract_link_targets`.

### N5 — `header-body-coherence` re-declares git status constants and mis-names them

`header_body_coherence.py` adds `_NEW_OR_MODIFIED_STATUSES = ("A","M")` and
`_RENAME_STATUS_PREFIX = "R"`, duplicating `_COMMIT_ADD_STATUS`,
`_COMMIT_MODIFY_STATUS`, `_COMMIT_RENAME_PREFIX` in `checks/common.py:369-371`.
The local variable is called `is_new_or_renamed` while the tuple means
"added or modified". Copy status `C` is not covered, so a copied PLAN.md skips
the commit gate — rare, since `-C` is off by default. Fix: export the three
constants from `common.py` and consume them.

### N6 — The commit surface takes the plan number from the title, the other surfaces from the folder

`header_body_coherence._run_commit` passes `staged_doc.plan_number` (parsed from
the `# Plan NNNNN:` heading) to `commit_scoped_level`, while
`_run_edit`/`_run_sweep` use the classifier's/folder's number. A plan in
`legacy_plan_allowlist` whose title heading is malformed is ADVISE at edit and
sweep but BLOCK at commit. Fix:
`plan_number_for_folder(staged_plan_md_folder(...))`, as the other commit-stage
checks do.

### N7 — `revalidate_corpus` reads content at a cache-derived path with normalisation only

`docs_qa/corpus.py:721` uses `authored_path` (no containment) and then
`read_text` at line 738. The inline comment justifies this on cost — but the
cost is `resolve()`; the lexical half (`is_relative_to` on the already
normalised path) is free and closes the `..`/absolute vectors, leaving only
symlinks. Worth taking the free half.

### N8 — `pointer-resolves` now follows symlinks when deciding existence

`_exists_within` → `contained_authored_path` → `candidate.resolve(strict=False)`
(`utils/authored_paths.py:108`). A documentation link that traverses a symlink
pointing outside the repository is now graded "does not exist", at BLOCK when
the link is new — the same unretryable-denial class the helper's docstring says
it fixed. No such symlink exists in this repo (`find . -type l` shows only
`.claude/init.sh -> ../init.sh` and venv internals), and the normal-mode
installer copies rather than symlinks, so this is a note for client installs
that symlink a docs tree.

### N9 — Archive exclusion re-keyed from `trees.agent` to `plan_workflow.directory`

`docs_qa/corpus.py:356-360` replaced the hardcoded `{agent_tree}/Plan/Completed`
test with `policy.plan_tree.is_archived(...)`. For a project whose
`documentation.trees.agent` is not the root of its `plan_workflow.directory`,
archived plans that used to be excluded are now indexed (and vice versa). The
new reading is the more principled one and is documented in the docstring; just
confirm it is in the upgrade guide's behaviour-change list.

### N10 — `release-blocked-plan` also judges archived plans

`document_rule_checks` → `tree_targets` yields COMPLETED/CANCELLED folders too,
and the only exemption is a terminal status. An archived plan whose header
rotted to `In Progress` gets a BLOCK-level finding on a historical record — the
thing `plan_link_resolves._run_sweep` explicitly avoids with
`if target.in_archive: continue`. Consistent with the pre-existing
`header-body-coherence` behaviour, so not a regression; flagging the asymmetry.

### N11 — Minor

- `release_blocked_plan.py`: `line.strip()[:120]` — unnamed truncation width in
  a module that otherwise names every constant.
- `plan_link_resolves.py`: `_MAX_REPORTED_LINKS` truncates the list without
  saying "and N more", so a reader sees ten and believes that is all.
- `utils/markdown_links.py:9-16` (adjacent, out of scope) claims the module
  "imports neither" QA package while line 16 imports `plan_qa.model`.
- `strategies/pipe_blocker/common.py:56-64`: removing `env` from the whitelist
  is right for a piped `env pytest`, but `pipe_blocker` does not unwrap, so a
  piped `env git log` or `env cat f` is now blocked although the wrapped command
  is whitelisted. Deliberate, documented, and the deeper fix is already named in
  commit `85b5adc4`'s message.

---

## Checklist results

| Item | Result |
| --- | --- |
| Bugs in check/strategy logic | D1 (fires on legitimate content), D2 (crash), D3 (gate cannot fire) |
| Security anti-patterns | None. No shell, `eval`, subprocess or credentials in scope. The bundle's direction is the opposite: `contained_authored_path` closes real existence/content oracles in `path-existence`, `pointer-resolves`, `quote-drift` and the plan-link resolver. |
| Tests alongside every change | Mostly yes, with four exceptions — `plan_qa/model.py`, `plan_qa/context.py`, `docs_qa/context.py`, `docs_qa/checks/quote_source_stale.py` changed with no test change. D2 and D3 sit in two of them. |
| Magic strings/numbers | Named throughout except N5 and N11's `[:120]`. |
| SOLID / Strategy Pattern | Clean. `is_excluded_source_file` was added to the `TddStrategy` protocol and implemented by **all 11** strategies with no registry or handler branching; `tdd_enforcement.py:377` consults it through the protocol. No `if/elif` on language names introduced anywhere in the diff. |
| Debug code, workarounds, TODOs | None — a grep of added lines for TODO/FIXME/HACK/XXX/workaround/print/breakpoint/pdb returns nothing. |

## Positives

- Visible TDD discipline: RED commits precede their fixes throughout
  (`0311a782` → `54368a76`, `4d0fcead` → `04825c74`, `79421f21` → `85b5adc4`).
- `header-body-coherence`'s EDIT→ADVISE / COMMIT→BLOCK move is argued from an
  unsatisfiable-gate analysis and is a net tightening (the check previously had
  no commit registration at all); the commit surface is tested end-to-end
  against a real git repo, including the inherited-violation ADVISE path.
- The 00419 N6 TDD fix is pinned by three tests, including the guard that the
  fix must not switch the declared layout off.
- `authored_paths` splits three genuinely different questions (normalise,
  contain, exist) and each call site in the diff states which one it wants and
  why — including the two places that deliberately choose normalise-only.

## Verdict

REQUEST CHANGES — D1 and D2 before the release ships; D3 is a one-line fix in
the same pass.
