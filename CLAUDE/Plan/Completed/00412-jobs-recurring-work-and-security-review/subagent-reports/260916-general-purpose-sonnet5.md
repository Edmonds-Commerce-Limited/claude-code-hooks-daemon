# Plan 00412 Worklist Audit — What Remains (260916)

Read-only audit of `260915-consolidated-defence-worklist.md` against git log,
`CLAUDE/Security/AsymmetricSiblingProtection.md`, `PLAN.md`, and
`JOURNAL/00412-Journal-26-09-16.md`.

## Method note

The worklist explicitly says class instance-counts must not be summed (many
findings belong to 2 classes) and that "primary class" is the unit that
determines Detector buildability. Classification below is at **class
granularity** (18 classes + "findings that fit no class" + the cross-cutting
split), citing individual findings by ID where their status diverges from
their class.

## 1. Counts

- **(a) BUILDABLE NOW**: 17 of 18 class-level Detectors (classes 2-18) are
  unbuilt and explicitly rated buildable, plus several individual fixes
  inside those classes with no owner decision required (~30+ individual
  findings).
- **(b) OWNER-GATED**: 1 finding blocked (F-PRIV-4), plus ~10 named fixes
  across classes 2-4, 6, 9, 11, 13-18 whose *Detector* is buildable but whose
  *fix* changes gate behaviour for installing projects.
- **(c) ALREADY DONE**: class 1 (`asymmetric-sibling-protection`) Detector +
  7 of 13 instances, `authored-path-resolution` class (excluded from
  worklist), D-PUB-4, D-PUB-2, F-HYG-1, F-DEPL-2, F-DEPL-4.
- **(d) REJECTED / NOT A DEFECT**: D-SEC-1's `path_is_protected` pairing
  (class 1 row); 2 one-off findings noted as "not a finding"
  (`.claude/worktrees-archive/`, `pipe_blocker` false-positive on
  `grep '<('`).
- **(e) UNCLEAR**: F-DEPL-4's exact current site (line refs rotted after
  `install.py` split into `install/`) — location needs re-derivation, not a
  decision.

## 2. BUILDABLE NOW — class Detectors + individual fixes with no gate change

Git log confirms **only class 1's Detector (`declared_invariant_pairs`) has
been built**. Classes 2-18 are entirely unbuilt; PLAN.md Task 3.4 is still
`🔄` and the journal's "00412's buildable worklist is now exhausted"
(JOURNAL 26-09-16, line 386) refers only to class 1's declared-pair rows,
not the other 17 classes.

| Class                                             | Detector (buildable now)                                                                                                                                   | Representative buildable fix (no gate change)                                                                                                                                                                                                                                                                   |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 follow-up                                       | D-SEC-1 corrected fix: **redact matched bytes in the deny message rather than exclude the file** (per register's rejection, not "add `path_is_protected`") | `handlers/pre_tool_use/sensitive_content.py:884`                                                                                                                                                                                                                                                                |
| 2 `guard-self-disablement-unwatched`              | (a) commit-time `RULE CHANGE:` gate, (b) SessionStart config-drift reconciliation, (c) schema check on handler options                                     | `handlers/registry.py:577` (unvalidated `setattr`)                                                                                                                                                                                                                                                              |
| 3 `enforcement-path-executes-unverified-code`     | Detector: PATH-mutation+bare-argv0 rule                                                                                                                    | D-DEP-01 fix (ship `eslint-wrapper.ts` or resolve `tsx` from fixed path) — `handlers/post_tool_use/validate_eslint_on_write.py:296-327`                                                                                                                                                                         |
| 4 `fail-open-when-check-cannot-run`               | Inventory-shaped Detector (~6 hand-maintained entries)                                                                                                     | none fully gate-free; measurement (commit-judging latency) should precede the owner decision                                                                                                                                                                                                                    |
| 5 `absence-indistinguishable-from-clean`          | Part 1 (report the denominator) **has zero false positives — no decision**                                                                                 | `scripts/qa/llm_qa.py` / `check_sensitive_content.py:145-146,176-183`                                                                                                                                                                                                                                           |
| 6 `outcome-reachable-by-an-unenumerated-spelling` | Table-driven invocation corpus + doc-resolves-to-rule-ID checker (ship first)                                                                              | Low-noise deny rows: `filter-branch`/`filter-repo`, `reflog expire`, `gc --prune=now`, `checkout -f`, `switch -f`, `docker run -v /:`, `crontab -r`, `.git/` writes — `handlers/pre_tool_use/destructive_git.py:87-165`                                                                                         |
| 7 `interpolation-into-another-language`           | `audit_shell.py` + Python-AST `JoinedStr` rule                                                                                                             | D-EXEC F1 (`.claude/init.sh:1423`, pass via argv not `-c`), F2 (`scripts/run-qa-runner.sh:63-83`, quote `$CMD`), F4 (`lint_on_edit.py:474-476`, `staged_lint_gate.py:288-289`, use the correct line one below), D-NET N3 (`remote_docs/capture.py:162-186`, use `yaml.safe_dump`) — all pure code-quality fixes |
| 8 `exemption-scope-drift`                         | `check_exemption_dialect.py`, 3 rules                                                                                                                      | F-EXPT-1/2 fixes: `strategies/pipe_blocker/common.py:56` drop `^env\b`; `strategies/security/common.py:3-23` route `SKIP_PATTERNS` through `path_exclusion.is_path_excluded`                                                                                                                                    |
| 9 `daemon-as-reader-skips-protected-set`          | `check_protected_path_readers.py`, **must land RED before any fix**                                                                                        | D-SEC-2 fix: stop echoing `match.group(0)` — `scripts/qa/check_sensitive_content.py:307`                                                                                                                                                                                                                        |
| 10 `irreversible-publication-surface-inventory`   | Hand-maintained surface list + equality check                                                                                                              | D-PUB-1 fix: add `gh release create/edit`, `gh gist create`, `gh pr review --body`, `gh repo edit --description` to `_GH_BODY_PATTERN`                                                                                                                                                                          |
| 11 `check-enumerates-from-registry-it-polices`    | `check_deploy_declarations.py` (seeded exemption list)                                                                                                     | F-DEPL-1: add 4 undeclared asset categories to `CLIENT_OWNED_ASSETS`                                                                                                                                                                                                                                            |
| 12 `write-time-guard-with-no-batch-equivalent`    | `check_git_blobs.py` (Detector buildable now)                                                                                                              | —                                                                                                                                                                                                                                                                                                               |
| 13 `executable-content-outside-the-lock`          | Per-route rules (build-system pin, pre-commit SHA pin, optional-import degradation)                                                                        | D-DEP-02 pin `setuptools`/`wheel` with `==`; D-DEP-07 pin pre-commit hook to 40-char SHA                                                                                                                                                                                                                        |
| 14 `fetch-then-execute-unpinned`                  | 3 rules over `*.sh`/`*.py`/CI; **downgrade-flag grep is cheapest in corpus, ship first**                                                                   | D-NET N7: fix `2>/dev/null` silencing in `install.sh:100-104`                                                                                                                                                                                                                                                   |
| 15 `unbounded-work-on-input-not-sized`            | Widen `test_git_spawns_are_bounded.py`                                                                                                                     | D-EXEC F5: add `timeout=` to `background_harvester.py:275`, `cli.py:3185`                                                                                                                                                                                                                                       |
| 16 `response-trusted-beyond-request-validated`    | Flag `urlopen` without redirect handler                                                                                                                    | D-NET N1 fix: `build_opener()` disallowing redirect scheme change — `remote_docs/fetchers.py:98-116`, `install/relay_deploy.py:272-276`                                                                                                                                                                         |
| Cross-cutting Split 1/2                           | `doc-claims-a-rule-that-has-no-id` (ship first), suppression-comment rule                                                                                  | Fixes `CLAUDE/ARCHITECTURE.md:30` (`rm -rf` claim), `nosec B603` comment                                                                                                                                                                                                                                        |

## 3. OWNER-GATED — decision needed

| Finding                                                                                             | Decision                                                                                                                                                |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F-PRIV-4**                                                                                        | Already written up, `ffe86b0c`/DECISION-secret-guard-module-path-false-positive.md — how to narrow a dotted-module-path match without losing protection |
| **D-PUB-3** (class 4)                                                                               | Fail-closed on oversized/unreadable `gh` body file — new refusal surface in every install                                                               |
| **F-HYG-3** (class 1/9)                                                                             | New deny in `staged_lint_gate.py:249-250` when a staged path is protected — new refusal surface                                                         |
| Forwarder `${VAR:-default}` (2 sites, class 7)                                                      | DECISION-forwarder-interpolation-contexts.md — recommends option B (assign default to plain var first)                                                  |
| Degraded-mode blast radius (class 2/4, F-BYPS-3)                                                    | DECISION-degraded-mode-guard-surface.md — which handlers should survive a bad config                                                                    |
| Class 3: `project_handlers.path` containment                                                        | Removing a documented config capability                                                                                                                 |
| Class 3: `relay_binary` validator / digest-at-exec                                                  | Must be advisory-first, not per-call (risk of denying every hook)                                                                                       |
| Class 4: any fail-open → fail-closed conversion                                                     | Behaviour change on slow/bad-config installs                                                                                                            |
| Class 6: broad `rm -rf`, `npm install`, `env`/`printenv`, `git rebase` denies                       | Reported by reviewers as too noisy to ship as hard denies                                                                                               |
| Class 12: purge git-history residue (F-PRIV-1/2)                                                    | `git filter-repo` + force-push over 3,818 commits                                                                                                       |
| Class 17: escaping-root semantics (D-PATH-4)                                                        | "Does not exist" vs error vs new Finding type — changes agent-visible messages                                                                          |
| Class 18: `ccy_supervisor` armed-by-default (F-DEPL-5), reference-repo `auto_pull: True` (D-NET N6) | Flip tri-state default from capability to advisory                                                                                                      |

## 4. ALREADY DONE

`authored-path-resolution` (complete, excluded from worklist); class 1
Detector + rows: env whitelist (`85b5adc4`), worktree verbs (`55f374e8`),
prose-as-command (`c23b1b8c`), unguarded refresh (`a6ce7bb7`), tilde escape
(`f280153f`), gh bare-name anchor/D-PUB-4 (`8489b6dd`), message-file
reader/D-PUB-2 (`1a74bf90`), unguarded rmtree (`e8683948`), backup-pair/
F-DEPL-4 (`cef01a69`), F-HYG-1 (`886a7184`).

## 5. Staleness / contradictions found

1. **D-SEC-1, worklist line 824**: "Buildable now. D-SEC-1's fix is one
   call mirroring `staged_lint_gate.py:249`" is **stale/wrong** —
   `AsymmetricSiblingProtection.md:376-407` rejected exactly this pairing:
   adding `path_is_protected` to `sensitive_content.py` would let a secret
   in a protected file commit silently. The correct remaining fix is
   redacting the echoed match, not excluding the file (still open, class 9).
2. **JOURNAL 26-09-16:386** "00412's buildable worklist is now exhausted"
   is scoped only to class 1's declared-pair rows — reads misleadingly
   broad; classes 2-18 (the other ~16 Detectors) are untouched.
3. **F-GAP's "outward publication is covered"** vs D-PUB/F-BYPS — F-GAP's
   clean claim didn't test `gh release`; worklist resolves this as F-GAP's
   wording being broader than its evidence (documented at worklist:1584-1595,
   not a live contradiction needing action, but worth flagging since F-GAP
   is cited elsewhere as authoritative).
4. **PLAN.md** Task 3.4 remains `🔄` and all four Success Criteria are
   unchecked — the plan itself has not been closed.

## Key files

- `/workspace/CLAUDE/Plan/00412-jobs-recurring-work-and-security-review/subagent-reports/260915-consolidated-defence-worklist.md`
- `/workspace/CLAUDE/Security/AsymmetricSiblingProtection.md`
- `/workspace/CLAUDE/Plan/00412-jobs-recurring-work-and-security-review/PLAN.md`
- `/workspace/CLAUDE/Plan/00412-jobs-recurring-work-and-security-review/JOURNAL/00412-Journal-26-09-16.md`
