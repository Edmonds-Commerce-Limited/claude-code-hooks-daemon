# Plan 00484: DBF toolchain conformance assessment

This is the Task 2.1 assessment. It grades this repository against the vendored
[toolchain specification](../../../remote-docs/defence-before-fix.github.io/raw/TOOLING-SPEC.md)
(TOOLING 0.2.0) §4–§9. It also grades the
[detector specification](../../../remote-docs/defence-before-fix.github.io/DETECTOR-SPEC.md)
(DETECTOR 1.0.0) clauses that TOOLING §4.1 pulls in, for every detector a defence is routed
through. Each clause is graded MET, PARTLY MET, NOT MET or NOT APPLICABLE, with evidence from
the current tree on `main` (734695b9b). The grading is deliberately strict: where the plan's
mapping does not hold, the grade says so.

## Freshness of the vendored specs

- **The vendored copies match upstream.** All five files under `remote-docs/defence-before-fix.github.io/` carry
  provenance frontmatter: fetched 2026-09-15, `stale_after: 2026-12-14`, licence CC-BY-4.0.
  `bin/hooks-daemon remote-docs check` reports "all vendored documents are fresh" (exit 0).
- That check only tests the age window, so I also fetched upstream into a scratch cache with
  the DBF plugin's `refresh-spec.bash --force` (`CLAUDE_PLUGIN_DATA=untracked/scratch/...`). No
  tracked file was touched.
  - Upstream versions are unchanged: SPEC 1.0.1, DETECTOR 1.0.0, TOOLING 0.2.0.
  - Upstream `TOOLING-SPEC.md` hashes to `64d5dc76…bd3`, the vendored `source_sha256`, and the
    project prompt matches too.
  - SPEC and DETECTOR-SPEC are HTML conversions of the same versions. Plan 00467's
    EVALUATION.md, Criterion 4, records this already.
- No refresh was needed, and none was done.

## What is graded: the detectors and the two levels

TOOLING §9.1 requires two separate verdicts:

- **Project level:** this repository's own assembled toolchain. That is the daemon running
  dogfooded on its own repository, plus `scripts/qa/` behind `llm_qa.py`, plus the third-party
  tools that `llm_qa.py` runs.
- **Artefact level:** what a consuming project gets when it installs the daemon and builds
  nothing else around it. That is the handlers, project handlers, `explain-rule`,
  `generate-docs`, CLAUDE.md injection and `.claude/hooks-daemon.yaml`. `scripts/qa/` is not
  shipped.

The detectors that defences are routed through:

| Ref | Detector                                                      | What it carries                                                                        |
| --- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| A   | The daemon's handler engine (hook-time)                       | 121 rule IDs (`explain-rule --list`), library handlers and `.claude/project-handlers/` |
| B   | The bespoke `scripts/qa/check_*.py` and `audit_*.py` checkers | The project's own QA rules (magic values, error hiding, hook contract, fail-open, …)   |
| C   | Semgrep, with the rule directory `scripts/qa/semgrep/`        | 9 bespoke rule IDs in 6 rule files                                                     |
| D   | ruff, mypy, pyright, bandit, shellcheck                       | Their native catalogues only. No bespoke rule is hosted in any of them                 |

Black is a formatter and pytest and the smoke test are runners. Neither kind is a detector
route.

**Where the plan's mapping does not hold:**

- "Enumeration = handler listing / HOOKS-DAEMON.md" is only half true.
  - `.claude/HOOKS-DAEMON.md` lists handlers but contains **zero rule IDs**.
  - `explain-rule --list` lists IDs, but it is derived from installed code, not from the active
    config.
- "Identifiers = rule IDs" holds for detector A only. B's IDs resolve nowhere.
- "Self-audit = test_claude_md_guidance_coverage.py" is not the right test. That test audits
  guidance verdicts. The §8.1 guard is `tests/unit/test_rule_parity.py`, and the §8.2 guard is
  `tests/integration/test_dogfooding_config.py`.

## Summary: TOOLING-SPEC (project level; artefact level where it differs)

| Clause | Obligation (short)                                                     | Grade (project)          | Artefact   | One-line evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------ | ---------------------------------------------------------------------- | ------------------------ | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4.1    | No defence routed through a non-conforming detector                    | NOT MET                  | NOT MET    | A's 9 identifier-less deny paths now print one (G5, Task 3.1a); B fails D5.2; D cannot host bespoke rules (see matrix)                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 4.2a   | Every printed identifier resolves offline                              | PARTLY MET               | MET        | `explain-rule` resolves every handler rule ID offline, including a client's project-handler rules, and since Task 3.1a the plan-QA and docs-QA check IDs too (G15, `rule_explain/checks.py`); since Task 3.1b (G6) B's IDs resolve too, through `llm_qa.py --explain <ID>` (`:2688`), so the rest of the gap is the wrapped third-party tools' own identifiers                                                                                                                                                                                       |
| 4.2b   | Remediation docs ship with the code, version tracked together          | MET                      | MET        | `Rule` objects live in handler source (`core/rule.py`, `get_rules()`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 4.2c   | A defined place for a new rule's docs                                  | MET                      | MET        | Handlers: `Rule(blocked, why, fix, verbose)`. B (since Task 3.1b): an entry in `scripts/qa/qa-rules.json`, which `test_qa_rules.py` requires for every rule a checker prints                                                                                                                                                                                                                                                                                                                                                                         |
| 4.2d   | Docs state the correct construction                                    | PARTLY MET               | MET        | Handlers: `test_rule_parity.py:180` requires a non-empty `fix`. B (since Task 3.1b): a `fix` per ID in `qa-rules.json`, and in review round 1 every entry was checked by hand against its checker's own message and remediation (about forty were wrong or loose and are corrected). Nothing mechanical ties a fix to what the checker does, so the text can drift again: PARTLY MET, not MET                                                                                                                                                        |
| 4.3a   | Forbid (disable or block) every route that bypasses the record         | NOT MET                  | NOT MET    | 6 `MUST_*_BECAUSE` in-band hatches; inline suppressions are KEPT BY DESIGN (owner rulings B1, B2), not forbidden: 113 directive lines remain (65 `nosec`, 12 `pragma: no cover`, 36 `shellcheck disable`; the 78 of the deletion pass counted the Python directives only, see `SUPPRESSIONS.md`) after 228 were deleted, and since Task 3.1b each must carry a reason, enforced by `check_inline_suppressions.py` (`judge_comments`), registered as `llm_qa.py inline_suppressions`. So this stays a declared known gap against 4.3, not conformance |
| 4.3b   | Irreducible cases directed to the project record                       | NOT MET                  | NOT MET    | Hatches send the agent to the command line or a file comment, never to the config                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 4.4a   | Entry point meets D5.1–5.4 for every defence                           | NOT MET                  | PARTLY MET | The hook path meets it; `llm_qa.py` itself still has no single-file subset (only `--path FILE` on three checkers, see D5.2 under B), so this stays NOT MET at project level                                                                                                                                                                                                                                                                                                                                                                          |
| 4.4b   | Entry point prints every identifier unaltered                          | PARTLY MET               | MET        | A deny prints `BLOCKED [R-…]`; since Task 3.1b `llm_qa.py` prints the first 5 findings of a failing tool with their IDs and the absolute report path (`:1455`), but not every ID, and the 3 row-key checkers have none                                                                                                                                                                                                                                                                                                                               |
| 4.5a   | Detectors run before runners                                           | MET                      | N/A        | MET since Task 3.1b: every runner (`RUNNER_TOOLS`, `llm_qa.py:898`) is registered after every static detector (`:843`), and `resolve_tools` moves a named runner after the detectors (`:1623-1625`). Pinned by `tests/unit/qa/test_llm_qa_detectors_first.py`                                                                                                                                                                                                                                                                                        |
| 4.5b   | A detector failure stops lower levels counting                         | MET                      | N/A        | MET since Task 3.1b, in the amended form (every tool still runs, so the other findings are not hidden): once a detector has failed, `_run_tools` marks each runner that passed `NOT MEANINGFUL: detector failed` (`mark_not_meaningful`) and leaves it out of the pass count (`format_verdict`); a runner that failed itself stays a failure; the provenance record keeps the runner's real result so `--resume` still reuses it                                                                                                                     |
| 5.1a   | List every active defence without running it                           | PARTLY MET               | PARTLY MET | `explain-rule --list` lists all installed rules, disabled ones included; HOOKS-DAEMON.md is active-only but has no IDs. Task 3.2 adds `hooks-daemon defences --json`, active-only with IDs ([reference](../../../docs/guides/TROUBLESHOOTING.md#cli-command-reference))                                                                                                                                                                                                                                                                              |
| 5.1b   | Listing carries ID and a terse statement                               | PARTLY MET               | PARTLY MET | `explain-rule --list` does (`cli.py:8553-8557`); HOOKS-DAEMON.md does not; `defences` carries the ID and the `qa-rules.json` statement for the three batch checkers, and the other B checkers are absent                                                                                                                                                                                                                                                                                                                                             |
| 5.1c   | Listing gives the route to full docs                                   | PARTLY MET               | MET        | `explain-rule <ID>`, stated once in the CLAUDE.md header and, since Task 3.1a, as the last line of `explain-rule --list`; a batch-check row's route is `llm_qa.py --explain <ID>`, and nothing for the B checkers that are not rows                                                                                                                                                                                                                                                                                                                  |
| 5.2    | Listing derived from the active config                                 | PARTLY MET               | PARTLY MET | `--list` instantiates classes with no config (`lookup.py:84-88`); `docs_generator.py:324-329` skips the tag gates that `registry.py:244-262` applies                                                                                                                                                                                                                                                                                                                                                                                                 |
| 5.3    | The project's own defences appear alongside bundled ones               | PARTLY MET               | PARTLY MET | Since Task 3.1e the rules of three B checkers (`audit_error_hiding`, `check_sensitive_content`, `check_inline_suppressions`) are `batch-check` rows of `hooks-daemon defences`, declared in `qa-rules.json`; the other B checkers are not Defences by the coordinator's call, so they stay unlisted; the 4 project handlers that denied with no rule now declare one (G5), and `hooks-daemon defences` lists the Defences only (owner ruling C1)                                                                                                     |
| 6.1    | A defined record location the toolchain loads                          | PARTLY MET               | MET        | `.claude/hooks-daemon.yaml` is loaded (`config/models.py:2717`); B's exception files are named by `QA_EXCEPTION_FILES` (`config/exceptions_listing.py:39`) and listed by `exceptions`                                                                                                                                                                                                                                                                                                                                                                |
| 6.2a   | Every exception carries a justification; none defaulted, none omitted  | NOT MET                  | NOT MET    | `options: dict[str, Any]` (`models.py:58-78`); `enabled: bool` has no reason (`:72`); `never_want.reason` defaults to `""` (`:2111`)                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 6.2b   | Names hazard and scope; generic reasons rejected by a documented check | NOT MET                  | NOT MET    | No generic-reason check anywhere in `src/` or `scripts/`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 6.3    | Record enumerable by the same means as the defences                    | PARTLY MET               | PARTLY MET | `hooks-daemon exceptions [--json]` lists config exceptions, disabled and downgraded handlers, in-file size hatches and eight QA exception files (`cmd_exceptions` in `daemon/cli.py`, `config/exceptions_listing.py:97,132,162`). Not listed: inline `nosec` / `noqa` / `type: ignore`, and exemption constants hard-coded in scripts                                                                                                                                                                                                                |
| 6.4    | SHOULD: documented defaults                                            | MET                      | MET        | `hooks-daemon.yaml.example`, `init_config.py`, `Handler.get_default_enabled`                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 7.1    | SHOULD: terse per-defence summary with ID and docs route               | PARTLY MET               | MET        | Promoted prose sections now end with an `IDs:` line (G13, `claude_md_injector._with_rule_ids`); B's rules are still absent at project level                                                                                                                                                                                                                                                                                                                                                                                                          |
| 7.2    | SHOULD: delivered automatically into a delimited generated region      | MET                      | MET        | The `<hooksdaemon>` block, regenerated on restart (`core/claude_md_injector.py`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 8.1    | Release fails if a bundled defence lacks resolvable docs               | n/a (artefact)           | MET        | `test_rule_parity.py:162-227` on the full gate, which RELEASING.md:285 requires; since Task 3.1a it also walks every plan-QA and docs-QA `CHECK_ID` (G15) and the project's own deny handlers (G5)                                                                                                                                                                                                                                                                                                                                                   |
| 8.1f   | Family-page pattern audit                                              | n/a                      | N/A        | One ID per rule; there are no family pages                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 8.2    | Bundled defences active on own source; release fails otherwise         | n/a (artefact)           | MET        | `test_dogfooding_config.py:117` asserts every production handler is enabled here                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 9      | Partial conformance not described as conformance                       | MET                      | MET        | README and `pyproject.toml` make no DBF claim at all (checked by grep)                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 9.1    | The two levels graded and declared separately                          | N/A (no declaration yet) | N/A        | Becomes binding at Task 3.3; this document grades both                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 9.2    | Known gaps recorded with the declared version                          | N/A (no declaration yet) | N/A        | Becomes binding at Task 3.3; the text is drafted below                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

**Project-level verdict: not conforming.** Seven clauses are NOT MET (4.1, 4.3a, 4.3b, 4.4a,
5.3, 6.2a and 6.2b in the table), so the toolchain is not conforming, and it is not conforming
with agent support either. Most of the gap is in the QA
layer (B, D, `llm_qa.py`) and in the governance of exceptions. The handler layer is close.

## Summary: DETECTOR-SPEC matrix (the clauses TOOLING §4.1 pulls in)

| Clause            | A: handler engine | B: scripts/qa checkers | C: Semgrep (wrapped) | D: ruff, mypy, pyright, bandit, shellcheck |
| ----------------- | ----------------- | ---------------------- | -------------------- | ------------------------------------------ |
| 4.1 bespoke rules | MET               | MET                    | MET                  | NOT MET (see gap G10)                      |
| 4.2 harness       | PARTLY MET        | PARTLY MET             | MET                  | –                                          |
| 4.3 stable ID     | MET               | MET                    | MET (wrapped)        | –                                          |
| 4.4 SHOULD        | PARTLY MET        | NOT MET                | N/A                  | –                                          |
| 5.1 local         | MET               | MET                    | MET                  | –                                          |
| 5.2 single file   | PARTLY MET        | PARTLY MET             | MET                  | –                                          |
| 5.3 output        | MET               | MET                    | PARTLY MET           | –                                          |
| 5.4 not hosted    | MET               | MET                    | MET                  | –                                          |
| 6.1 resolution    | MET               | PARTLY MET             | MET                  | –                                          |
| 6.2 offline       | MET               | N/A                    | N/A                  | –                                          |
| 6.3 docs ship     | MET               | N/A                    | N/A                  | –                                          |
| 6.4 SHOULD        | MET               | N/A                    | N/A                  | –                                          |
| 6.5 families      | N/A               | N/A                    | N/A                  | –                                          |
| 7.1 suppression   | MET               | PARTLY MET             | MET                  | –                                          |
| 7.2 SHOULD reason | PARTLY MET        | PARTLY MET             | NOT MET              | –                                          |

### Grade counts

| Scope                                 | MET | PARTLY MET | NOT MET | N/A |
| ------------------------------------- | --- | ---------- | ------- | --- |
| TOOLING, project level (29 rows)      | 7   | 11         | 6       | 5   |
| TOOLING, artefact level (29 rows)     | 13  | 6          | 5       | 5   |
| DETECTOR matrix, A + B + C (45 cells) | 22  | 11         | 2       | 10  |
| D (one row, a classification)         | –   | –          | 1       | –   |

Section 8 counts as N/A at the project level, because TOOLING §9.1 says it bears on the
artefact grade only. **Artefact-level verdict: not conforming either**, with five MUSTs NOT
MET: 4.1, 4.3a, 4.3b, 6.2a and 6.2b.

- Closing G4 (justifications), G5 (identifiers) and G11 (harness and single-file runs) would
  leave §4.3 as the only artefact-level blocker. That clause covers the in-band hatches, G2
  and G3.
- Whether those hatches are a bypass at all is the owner's ruling under G2.

## Per-clause detail: TOOLING-SPEC

### 4.1: every routed detector conforms

- **A: the handler engine.** It is the closest of the four.
  - **D4.1 MET.** `.claude/project-handlers/` handlers register in the same chain, with the
    same standing (`CLAUDE/PROJECT_HANDLERS.md`).
  - **D4.3 MET, with G5 closed in Task 3.1a (review round 1 S4).** The grade moved from PARTLY
    MET once a structural test existed: `tests/plugins/deny_carries_rule_id.py` wraps `handle` on
    every library and project handler class and fails the test that provoked any deny whose
    reason lacks `BLOCKED [R-...]` or names an ID the handler's `get_rules()` does not declare
    (no handler is exempt). It judges every deny a unit test provokes,
    wherever the reason was built, so the claim is as strong as the coverage gate. Running it
    caught further identifier-less deny paths in `destructive_git`, `sensitive_content`,
    `staged_lint_gate`, `remote_docs_commit_gate`, `remote_docs_provenance`,
    `remote_docs_routing` and `conflict_marker_commit_gate`, all now filed under a declared
    rule (`R-GIT-DESTRUCTIVE-UNREADABLE` is new). The nine deny paths found first
    printed no identifier and now do. The five library handlers
    (`DispatchDeclarationHandler`, `SubagentReportSizeBlockerHandler`,
    `SubagentReportPathVerifierHandler`, `CronStopEnforcerHandler` and
    `CronSubagentStopEnforcerHandler`) and the four project handlers (`ruff_format_blocker`,
    `enforce_llm_qa`, `plan_done_requires_holding_area` and `release_blocker`) declare a rule and
    print `BLOCKED [R-...]`. `AutoApproveReadsHandler`, the one handler that had been
    allowlisted, now declares `R-PERMISSION-REQUEST-NON-READ-TOOL` for its defensive deny, and
    no allowlist remains.
  - **D4.2 PARTLY MET.** No route runs one rule alone against supplied input.
    - `hooks-daemon probe --file payload.json` sends one payload through the real entry point.
      It is local and needs no infrastructure, but it runs the whole chain, so other handlers
      can answer first.
    - Single-handler observation exists only as a pytest unit test, or as
      `test-project-handlers`, which runs all of them.
  - **D5.2 PARTLY MET.** A content handler judges one tool call. There is no
    "check this file" invocation, and no way to sweep the existing tree with a bundled content
    defence such as `qa_suppression`, `error_hiding_blocker` or `security_antipattern`. The
    method's sweep step therefore cannot use them.
- **B: scripts/qa checkers.**
  - **D5.2 PARTLY MET since Task 3.1b (G8 phase 2).** `--path FILE` judges one file in
    `check_magic_values.py` (`run_single_file`, `:647`; the tree run's skip rules are now one
    function, `out_of_scope_reason`, so the two cannot disagree), `audit_error_hiding.py`
    (`audit_single_file`, exclusions applied as in the tree run) and `audit_shell.py`
    (`run_single_file`). Findings go to stdout (JSON with `--json`), no repository artefact is
    written, and a missing file, a directory, a file of another kind or a file inside the
    repository that the tree run does not judge FAILS rather than passing vacuously. In review
    round 1 (S4) the two audit scripts gained their own `out_of_scope_reason`, which reuses the
    tree run's collectors (`collect_workspace_python_files` plus `collect_shell_files`; the
    default scan directories and `_is_excluded`), so a test module under `audit_error_hiding.py`
    or the root `init.sh` under `audit_shell.py` is now refused. A file outside the repository has
    no tree-run verdict to match and is judged as given. Pinned by
    `tests/unit/qa/test_qa_single_file_subset.py`. The other
    checkers still take directories only; `check_authored_path_stat.py:300-303` still fails as
    vacuous on a file. They are the known gap.
  - Before: no checker accepted a file. `--path` and `--root` took directories.
  - **D4.3 MET since Task 3.1b (G6), with one note.** Every checker prints a stable rule ID,
    and each resolves through `qa-rules.json` (see 4.2). `check_fail_open_inventory`,
    `check_dangerous_invocation_corpus` and `check_declared_invariant_pairs` print one rule
    ID of their own per violation; their ROW keys remain data, not identifiers. The `rule`
    strings are not namespaced (`silent-pass`, not `R-...`), and a few IDs are shared by two
    checkers (`unreadable-file`, `marker-missing-reason`, `handler-ref-unknown`), so an ID
    names a class of finding rather than one script.
- **C: Semgrep.** Natively, Semgrep's `check_id` is prefixed with the path of the rule file,
  which D4.3 names as unstable. The wrapper strips the prefix back to the author's `id:`
  (`run_semgrep_check.sh:101`), so the wrapped pair holds (TOOLING 4.1 point 1).
- **D: third-party catalogues.** ruff, pyright and shellcheck cannot host a bespoke rule.
  mypy and bandit could through plugins, but none is used. TOOLING 4.1 point 3 says no defence
  is routed through such a detector, although it may run as a check. `llm_qa.py` nonetheless
  treats their findings as blocking. See gap G10.
- **Verdict: NOT MET.** One failed detector fails the clause.

### 4.2: identifiers resolve offline

- **Verified.** `bin/hooks-daemon explain-rule R-PIPE-TO-TAIL` prints the full rule offline
  with no daemon running. It walks the installed package (`rule_explain/lookup.py:105-143`,
  `cli.py:8527-8582`), and it is case-tolerant and suggests near matches.
- **Every literal ID resolves.** Every literal `"R-…"` string in `src/` and
  `.claude/project-handlers/` resolves, including `R-ORCHESTRATOR-MAIN-THREAD-WRITE`, which
  `orchestrator_simulate` now declares in every mode.
- **Correct construction is enforced for handler rules.** `test_rule_parity.py:162-196`
  requires non-empty `blocked`, `why`, `fix` and `verbose`, and checks that every rendering
  carries the ID.
- **B's identifiers resolve since Task 3.1b (G6).** `scripts/qa/qa-rules.json` holds one entry
  per rule ID the `scripts/qa` checkers print (a statement, a fix and the scripts that print
  it), and `llm_qa.py --explain <ID>` prints it (`explain_rule`, `llm_qa.py:2688`;
  `explain_command`, `:2709`); `--explain` with no ID lists them all. A `family:name` ID such
  as `public-pattern:aws-access-key` resolves to its family. `tests/unit/qa/test_qa_rules.py`
  DISCOVERS the IDs from the checkers' source (a `RULE` constant, `rule=`, a `"rule":` key, an
  assignment to `rule`, `_add(node, "<id>", ...)`, the keys of `VIOLATION_TYPES`) and fails if
  a checker prints an ID with no entry, an entry names a rule no checker prints, or an entry's
  `checks` list differs from the scripts that print it. **Review round 1 (B1) found that the
  first version missed IDs it could not read:** `audit_error_hiding.py` built six of them as
  `f"shell-{pattern.name}"` (`shell-|| true` and five more), none was in the registry, and
  `--explain` said no checker printed them. They are now `shell-or-true`, `shell-or-colon`,
  `shell-set-plus-e`, `shell-redirect-all-to-null`, `shell-discard-both-streams` and
  `shell-empty-err-trap`, a pattern with no declared ID raises, and the discovery now FAILS on an
  f-string, a concatenated or undefined constant, a lookup it cannot resolve, or an ID that is not
  kebab-case instead of skipping it. It follows imported constants and module dict lookups, which
  found a seventh missing entry (`plan-stats-arithmetic`) and one entry for a rule no checker ever
  emitted (`warning-instead-of-error`, deleted). The three row-key checkers
  (`check_fail_open_inventory`, `check_dangerous_invocation_corpus`,
  `check_declared_invariant_pairs`) print a single `rule` of their own
  (`fail-open-inventory`, ...) in each violation, and those resolve; their ROW keys are data
  and are not identifiers. Not covered: the identifiers of the wrapped third-party tools
  (ruff, mypy, pyright, bandit, shellcheck, Semgrep rule IDs), which are theirs to document,
  and the plan-QA and docs-QA check IDs, which `bin/hooks-daemon explain-rule` resolves
  (G15). `check_signal_targets.py` renamed four constants to `RULE_*` so the discovery sees
  them.
- **4.2d is PARTLY MET (review round 1, B3).** Of 13 entries the reviewer sampled, 4 were
  wrong (`silent-pass`, `raw-signal`, `unproven-process-handle`, `kill-command`). All entries were
  then compared with the message and remediation each checker prints, and about forty were
  corrected, among them `malformed-allowlist-entry` (the fields are `id`, `reason` and `link`),
  `config-key-mismatch`, `missing-identifier`, `handler-claim-mismatch`,
  `undocumented-blocking-handler` and `unbounded-skip-list-membership`. The review was by
  hand, once. No test can tell that a fix describes the checker's real behaviour, so the grade
  is not MET.
- **B rows in `defences` (Task 3.1e).** Which `scripts/qa` checkers are Defences is a
  Defence-membership call, the coordinator's and not the owner's: only the batch form of a
  Defence handler is a row (`audit_error_hiding`, `check_sensitive_content`,
  `check_inline_suppressions`). Membership is the `batch_defences` map in `qa-rules.json`; a
  row is every rule that script prints, marked `kind: batch-check`, with the defect class of
  its handler counterpart: the class and the enabled state come from the handler named in
  `batch_defences` (`error_hiding_blocker`, `sensitive_content`, `qa_suppression`), and a
  rule marked `meta` (checker plumbing: `config`, `unreadable-file`, `stale-exclusion`,
  `unauditable-file`) is not a row; there are 16 rows. `check_british_english` is not a row: a spelling convention is not
  a defect class, and `BritishEnglishHandler` declares none (coordinator ruling). 5.3 is now
  PARTLY MET at project level (counts 11 PARTLY MET, 6 NOT MET); 5.1b and 5.1c stay PARTLY
  MET because the other B checkers are not rows.

### 4.3: suppression routes that bypass the project record

The full inventory follows. "Bypasses" means a finding can be silenced without an entry
appearing in `.claude/hooks-daemon.yaml`.

| Route                                                                                      | Where it lives                        | Reason enforced?                                                                                                                                    | Bypasses record?            |
| ------------------------------------------------------------------------------------------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| `MUST_STASH_BECAUSE`, `MUST_SCAN_ROOT_BECAUSE`, `MUST_SQUASH_BECAUSE`                      | Bash command, one-shot                | Quoted, at least one character (`git_stash.py:38-41`); it matches anywhere in the command, an `echo` included                                       | Yes                         |
| `MUST_SKIP_SAFE_MODE_BECAUSE`                                                              | Bash command, one-shot                | **None.** A bare substring test (`bash_safe_mode.py:260`)                                                                                           | Yes                         |
| `MUST_EXCEED_COMMENT_SIZE_BECAUSE`                                                         | Inline comment in a tracked file      | Non-blank remainder of the line (`comment_size.py:104-130`). `-->` or `*/` counts as a reason, and one token covers the whole file on Write         | Yes                         |
| `MUST_EXCEED_PLAN_SIZE_BECAUSE`                                                            | HTML comment in PLAN.md               | Non-blank after `-->` is stripped (`plan_doc_size.py:111-123`); it downgrades to an advisory                                                        | Yes                         |
| `# nosec` (bandit)                                                                         | Inline, 232 uses (28 files in `src/`) | None. `run_security_check.sh` has no `--ignore-nosec`                                                                                               | Yes                         |
| `# nosemgrep`                                                                              | Inline, 0 uses                        | None. No `--disable-nosem`                                                                                                                          | Yes (latent)                |
| `type: ignore`, `pyright: ignore`, `noqa`                                                  | Inline, 23 `type: ignore` in tests    | None in QA. `qa_suppression` blocks them only on Write/Edit (`strategies/qa_suppression/python_strategy.py:12-25`); RUF100 flags only unused `noqa` | Yes                         |
| `# shellcheck disable=`                                                                    | Inline, 19 uses                       | None. No shell strategy exists in `qa_suppression`                                                                                                  | Yes                         |
| `# shell-audit: allow --`, `# capture-audit: allow --`, `# eacces-safe-exempt:`            | Inline markers defined by B           | Presence of text only (`audit_shell.py:86-87`)                                                                                                      | Yes                         |
| B's exception files (`error_hiding_exclusions.json` and 5 others)                          | Tracked files hard-coded per script   | Ranges from none (`error_hiding_exclusions.json`, `audit_error_hiding.py:928-983`) to presence only (`contract_allowlist.py:103-116`)               | Arguably (see 6.1)          |
| Hard-coded skip lists (`check_magic_values.py:617-629`), `pyproject.toml` per-file ignores | Source, and `pyproject.toml`          | None                                                                                                                                                | Partly                      |
| `enabled: false`, `mode: warn`, `exclude_paths`, `extra_whitelist`                         | `.claude/hooks-daemon.yaml`           | None (see 6.2)                                                                                                                                      | No: these are in the record |

- **The in-command `MUST_…_BECAUSE` question (Task 2.3).** In TOOLING terms an in-command
  justification is an **Exception that is never written to the project record**. It exists in
  the transcript and, at most, as one reason-less line in the rolling verdict log
  (`daemon/verdict_log.py:112-126`, `handler: None`, `rule: None`). That log is size-capped and
  untracked.
  - The spec names this case: "a finding can be silenced through it without an entry
    appearing in the Project record".
  - It is a bypass route, not a record entry, unless the owner rules that a one-shot
    command-line decision is not an Exception at all. The spec defines an Exception as a
    decision to leave an Instance unfixed; a one-shot `git stash` is arguably the
    Practitioner choosing a construction, not leaving one unfixed.
- **The in-file tokens are not borderline.** `MUST_EXCEED_COMMENT_SIZE_BECAUSE` and
  `MUST_EXCEED_PLAN_SIZE_BECAUSE` are inline suppression comments in exactly the sense §4.3
  names.
- **Placement matters.** Even a perfect `qa_suppression` cannot be the §4.3 blocking defence
  for the tree.
  - It sees only Write and Edit, and a Bash heredoc write reaches disk unexamined. CLAUDE.md
    says so itself, so the gap is admitted.
  - A careless agent writes heredocs routinely, so this is in scope, not a hostile shape.
  - The robust placement is a B-style detector that scans the tree under `llm_qa.py`, which
    judges the content wherever it came from.
- **Verdict: NOT MET**, on both 4.3a and 4.3b.

### 4.4: the entry point's reporting

- **The hook path meets D5.1–5.4.** The deny reason is the tool result the agent sees,
  verified with `probe` on a `git reset --hard` payload: `BLOCKED [R-GIT-RESET-HARD]`.
- **`llm_qa.py` does not.**
  - There is no file subset; only tool names or `changed` (`:806-844`).
  - Each tool's own output is discarded (`:1366-1367`).
  - **Task 3.1b (G8 phase 1).** A failing tool's summary now names its first
    `MAX_FINDINGS_SHOWN` (5) findings with their identifier, location and text, says how many
    there are, and prints the ABSOLUTE path of the full report (`failure_extras`,
    `llm_qa.py:1455`, called at `:1625`). Pinned by
    `tests/unit/qa/test_llm_qa_findings_in_summary.py`. A finding with no identifier key (the
    row-key checkers `check_fail_open_inventory`, `check_dangerous_invocation_corpus` and
    `check_declared_invariant_pairs`) is listed in the JSON only, not given an invented ID, and
    only the first five findings of a failing tool are named, so 4.4b stays PARTLY MET. The
    `--explain <ID>` hint is printed only when a shown ID resolves (review round 1, N2): a wrapped
    tool's own ID has no registry entry and gets no hint.
  - Before: the summary line carried a metric and a bare JSON filename, never the absolute
    directory, and no identifier. Identifiers reached the practitioner only if they opened the
    JSON.
- **The Semgrep wrapper rewrites `check_id`.** It does so towards the stable form, but strictly
  "unaltered" fails. This is noted rather than graded, because it is what makes C hold
  under 4.1.

### 4.5: ordering

**Both halves MET since Task 3.1b (G7).** Before: `TOOL_REGISTRY` ran `tests` sixth of the
static checkers and nothing marked a runner's result after a detector failure. Now
`RUNNER_TOOLS` (`llm_qa.py:898`: `tests`, `project_handlers`, `changed_tests`, `smoke_test`)
are registered after every detector (`:843`), `resolve_tools` stably puts runners last
whatever order they were named (`:1623-1625`), and `_run_tools` keeps running every tool but
marks each runner that PASSED `NOT MEANINGFUL: detector failed` and leaves it out of the pass
count (`mark_not_meaningful`, `format_verdict`). Review round 1 (S5) changed one case: a runner
that really failed after a failed detector used to be shown as `NOT MEANINGFUL` and left out of
the FAILED count; it now stays a failure, shown and counted as one. The exit code is non-zero
whenever anything failed, and the `--resume` and `--read-only` paths are pinned by tests (a
reused pass is marked, a recorded failure is re-run and stays failed). The recorded provenance
keeps the runner's real result. The tests are
`tests/unit/qa/test_llm_qa_detectors_first.py`. At the artefact
level the daemon ships no accept-changes invocation, so the clause is N/A there.

### 5.1–5.3: enumeration

| Surface                          | Derived from                                         | Active only?                                                                                                | IDs?                          | Docs route                    | Covers B? |
| -------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------- | ----------------------------- | --------- |
| `explain-rule --list` (121 rows) | Installed handler classes, built with no config      | No: it lists disabled handlers' rules too                                                                   | Yes                           | Implied (`explain-rule <ID>`) | No        |
| `.claude/HOOKS-DAEMON.md`        | Live config (`cli.py:3520`, `docs_generator.py:102`) | Mostly. It ignores `enable_tags`/`disable_tags` (`docs_generator.py:324-329` against `registry.py:244-262`) | **None** (0 matches for `R-`) | No                            | No        |
| CLAUDE.md `<hooksdaemon>` block  | Loaded handlers (`claude_md_injector.py:676-705`)    | Yes                                                                                                         | 96 of 121                     | One header line               | No        |

- **No single listing** meets all of 5.1: every active defence, with its ID, a terse
  statement and a docs route.
- **5.3 is PARTLY MET at project level since Task 3.1e.** `defences` includes the rules of
  three B checkers; the rest of B is not a Defence by the coordinator's call. The four project
  deny handlers that had no ID now declare one (G5).
- **HOOKS-DAEMON.md can disagree with registration.** The gap is the tag gates, not the
  absent-key default. Both `docs_generator` and `registry.config_skip_reason` treat an absent
  key as enabled, so they agree there; `get_default_enabled` governs only the template.

### 6.1–6.4: the project record

- **6.1 PARTLY MET.**
  - For the daemon, `.claude/hooks-daemon.yaml` is found upward and validated by pydantic
    (`config/models.py:2649-2737`). That is MET at the artefact level.
  - At project level, B reads six or more exception files hard-coded into each script.
    The record does not name them, and neither does any other file.
- **6.2 NOT MET.**
  - Exceptions in the live config carry no reason field. About 32 entries exist (for example
    `exclude_paths` on sensitive_content ×5, secret_file_guard ×7 and lint_on_edit ×3, and
    `collision_allowlist`). Their only justification is YAML comments, which the loader
    discards.
  - Handler `options` is `dict[str, Any]` copied onto the handler with `setattr`
    (`handlers/registry.py:323-334`), so no option can be validated for a reason.
  - Every deny message ends with "To disable: … (set enabled: false)". The probe output above
    shows it. That steers the reader to an unjustified record entry.
  - The one reason field that exists, `tool_policy.never_want.reason`, defaults to empty
    (`models.py:2111`), which the clause forbids.
- **6.3 PARTLY MET.**
  - `config`, `config --json` and `config-diff` are commands of the same kind as `explain-rule --list`. But `config` text mode shows only enabled and priority (`cli.py:2114-2180`).
  - No command lists exceptions with their justifications, the in-file hatches, or B's
    exception files.
- **6.4 MET.** Defaults are generated from the pydantic model (`config/loader.py:85-111`),
  and `test_default_enabled_template_consistency` pins the template.

### 7.1–7.2: agent context

- **7.2 MET.** The `<hooksdaemon>` region is delimited, marked as generated and refreshed on
  restart.
- **7.1 MET at artefact level, PARTLY MET at project level.**
  - The progressive table gives one row per rule, with ID, blocked, why and fix.
  - A promoted handler's prose section is emitted instead of rows, so its IDs used to appear
    nowhere in CLAUDE.md (examples: `R-PIPE-TO-TAIL`, `R-QA-SUPPRESSION`, `R-SEC-*`, `R-STOP-*`
    and `R-TDD-TEST-FIRST`). G13 (Task 3.1a) closes that: every promoted section now ends with an
    `IDs:` line.
  - B's rules are absent, which is the project-level gap.

### 8.1–8.2: self-audit (artefact)

- **8.1 MET.**
  - `test_rule_parity.py` requires every declared rule to be complete, unique, a declared
    constant (`:105-150`) and rendered with its ID (`:198`).
  - It also requires every handler with a `Decision.DENY` path to declare rules; there is no
    allowlist.
  - It is on the full gate, which RELEASING.md:285 requires before a tag.
  - The `Decision.DENY` source-marker discovery is a heuristic.
- **8.2 MET.** `test_dogfooding_config.py:117` fails when a production handler is not enabled
  in this repository's config.

## Per-clause detail: DETECTOR-SPEC (only where the matrix needs a note)

- **A D4.4 (SHOULD) PARTLY MET.** The parity test is a rule over the rules, but it covers the
  library package only. Project handlers are outside it, which is why four of them deny
  without an ID.
- **A D7.1 MET.** The in-band hatches are detectable by a rule the project can write in the
  detector itself: a project handler sees the same `command`, `content` and `new_string`. The
  verdict log is also a documented mechanical counter. It misses a bare
  `MUST_SKIP_SAFE_MODE_BECAUSE` and does not name the handler.
- **A D7.2 (SHOULD) PARTLY MET.** Five of the six hatches need some text. One needs none. None
  rejects a generic reason.
- **B D4.2 PARTLY MET.** Function-level harnesses exist (`check_source(source, path, root)` in
  `check_magic_values.py:579`, with tests in `tests/unit/qa/`). There is no CLI to run one rule
  alone, and running a harness means running the project's test suite.
- **B D5.3 MET since Task 3.1b.** A failing checker's summary carries the first findings with
  their identifiers and the absolute path of the remainder (`llm_qa.py:1455`). The checker run
  alone prints its own report or writes its artefact; the clause is judged on the command the
  practitioner ran, `llm_qa.py`.
- **C D4.2 MET.** `semgrep --config <one-rule.yaml> <file>` runs one rule natively. Two of the
  six rule files (`bounded-reads.yaml` and `short-refname.yaml`) have no fixture test. That is
  a missing red proof by the project, not a detector gap.
- **C D7.2 (SHOULD) NOT MET.** `nosemgrep` takes no reason.

## Threat-model check

Scope is set by CLAUDE/ARCHITECTURE.md § "Threat model: the agent is careless, not hostile"
and README "Guardrails, not armour". Clauses that would need a hostile-agent claim, or that
need a careful statement:

1. **4.3, "forbid every suppression route".** A hook-time guarantee that no suppression can
   reach the tree by any route, including `eval`, built strings or a stopped daemon, would be a
   hostile-agent claim. The in-scope reading is a deterministic tree scan under `llm_qa.py`. It
   judges content, not the route the content took, so it needs no claim about motive. Close
   §4.3 that way, never by hardening hooks against evasion.
2. **"Blocking".** Hook-time defences are blocking only while the daemon answers. The hook layer
   fails open by design (`CLAUDE/Security/FailOpenBoundaries.md`), and an agent can stop the
   daemon. The §9.2 declaration must say that a hook-time defence is a guardrail and not a
   guarantee. The release-time guards (`test_rule_parity`, `test_dogfooding_config`) do not
   share this caveat.
3. **Hardening the `MUST_…_BECAUSE` regexes against spoofed placement** (for example a token
   inside an `echo`) is a hostile-agent concern and out of scope. The in-scope defects are the
   missing or vacuous reasons. A careless agent writes `MUST_SKIP_SAFE_MODE_BECAUSE` with no
   reason because the handler accepts it.
4. **6.2's generic-reason check** is in scope. The spec itself says the check cannot verify
   truth (§6.2, last paragraph), so a conformance claim must not imply that it does.

## Gaps for the owner

Each gap is followed by the options (close / accept as known gap / out of scope) and my
recommendation.

| ID  | Gap                                                                                                                                                     | Clauses                    | Recommendation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1  | Inline QA suppressions (`nosec` ×232, `type: ignore`, `noqa`, `nosemgrep`, `shellcheck disable`, B's markers) are honoured and not forbidden            | T4.3                       | **Close.** Add a `scripts/qa` detector that fails on any inline suppression not covered by a reasoned record entry, and pass `--disable-nosem`. Move each justified `nosec` into a reasoned record. This is the in-scope placement (see threat-model point 1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| G2  | In-command `MUST_*_BECAUSE` hatches are Exceptions that never reach the record; `MUST_SKIP_SAFE_MODE_BECAUSE` needs no reason; `-->` passes as a reason | T4.3, T6.2, D7.2           | **Owner ruling needed** on whether a one-shot command decision is an Exception. Whatever the ruling, **close** the no-reason hatch and the closer bug, apply the 6.2 generic-reason check, and record handler, rule and reason in the verdict log. If the ruling is "Exception", also accept the in-command form as a declared known gap. **Status: CLOSED (owner ruling B1 keeps the hatches): no-reason hatch, `-->`/`*/` closer and generic-reason check fixed in commit 43bba0aa8; verdict-log recording is a separate item**                                                                                                                                                                                                                                                         |
| G3  | In-file `MUST_EXCEED_*_BECAUSE` tokens are inline suppressions                                                                                          | T4.3                       | **Close cheaply.** List them with `find-comment-blocks` or a record listing, and apply the generic-reason check. Or **accept** as a known gap: they live in reviewed, tracked files                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| G4  | No exception in `.claude/hooks-daemon.yaml` carries a justification, and deny messages advertise `enabled: false`                                       | T6.2                       | **Close in steps.** Accept `{pattern, reason}` alongside bare strings and advise on bare ones, then add a documented generic-reason check, then require reasons at the next major (a breaking config change). Change "To disable" to ask for a reason. **Partly closed (owner ruling B3, commit 0b8d3c0d3):** `{pattern, reason}` is accepted now on `exclude_paths` and `extra_whitelist`, a placeholder reason is a config error, and under `daemon.strict_mode` a reasonless entry is a warning plus a SessionStart config problem, not a load failure (a load failure would stop a client's daemon after upgrade); this repository's own config carries reasons. Remaining: required for everyone at the next major, and the "To disable" deny text still advertises `enabled: false` |
| G5  | Deny paths without an identifier: 5 library handlers (allowlisted) and 4 project handlers                                                               | D4.3, T4.2, T5.3           | **Close.** Give each a `Rule`, and extend the parity test to project handlers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| G6  | B's identifiers resolve nowhere and appear in no listing; B has no place for remediation docs                                                           | T4.2, T5.3, D6.1           | **Close** with Task 3.2: one registry of QA rule IDs with `fix` text, and `llm_qa.py --explain <ID>`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| G7  | `llm_qa.py` runs `tests` 6th and never short-circuits                                                                                                   | T4.5                       | **Close.** Order every static detector before every runner, and mark runner results as not meaningful after a detector failure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| G8  | `llm_qa.py` has no single-file subset and prints no identifiers or absolute output path; B's checkers take directories only                             | T4.4, D5.2, D5.3           | **Close in part.** Print the first N findings with IDs and the absolute JSON path. Add `--path FILE` to the checkers in phases                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| G9  | No single active listing with IDs and docs routes; `explain-rule --list` is not config-derived; HOOKS-DAEMON.md has no IDs and skips the tag gates      | T5.1, T5.2                 | **Close** with Task 3.2. Build one machine-readable listing from the loaded registry, apply the same four gates, and include project handlers and B                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| G10 | ruff, pyright and shellcheck cannot host bespoke rules, yet their findings block                                                                        | T4.1 point 3               | **Accept by declaration.** State that they run as checks and that no DBF Defence is routed through them. A Defence goes in A, B or C. Mark it out of scope for conformance                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| G11 | No single-rule harness for handlers, and no way to sweep the tree with a bundled content defence                                                        | D4.2, D5.2                 | **Close `probe --only <handler>`** (cheap). **Consider** a `scan <handler> <paths>` batch mode: it is what lets a DBF tool use the daemon's content defences for the sweep step                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| G12 | B's exception files are named by no record, and the record cannot be listed with its justifications                                                     | T6.1, T6.3                 | **Close** together with G4: a record listing command that names the files it reads                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| G13 | 25 promoted-handler IDs are missing from CLAUDE.md                                                                                                      | T7.1 (SHOULD)              | **Close.** Add one IDs line per promoted section, at a small token cost                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| G14 | Hook-time defences fail open, and a stopped daemon blocks nothing                                                                                       | Threat model, not a clause | **Out of scope.** State it in the declaration                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

**G1 status (owner ruling B2 applied: inline only, no central file or baseline).** Deleted 228
inline suppressions in commits `b2089aed8` and `ef8192afd` (193 inert `nosec` in tests and
scripts, 7 `nosec` in `src/` with no finding, 22 `type: ignore` and 6 `pragma: no cover`
replaced or dropped); 78 kept. Inventory, per-entry reasons and the reasonless lines still
needing a reason comment: [SUPPRESSIONS.md](SUPPRESSIONS.md).

**G1 closed in the form owner ruling B2 sets (Task 3.1b; review round 1 B2, S2, S6).**
`scripts/qa/check_inline_suppressions.py` fails on any `nosec`, `noqa`, `type: ignore`,
`nosemgrep`, `pragma: no cover`, `shellcheck disable`, `pyright: ignore`, `mypy: ignore-errors`,
`mypy: disable-error-code` or `pylint: disable` with no reason, and on the file-wide `ruff: noqa` and `flake8: noqa` forms
and `pyright: report...=` config comments. The pyright, mypy and pylint forms are read from the
`qa_suppression` handler's own list (`PythonQaSuppressionStrategy.forbidden_patterns`), so the
write-time and batch lists cannot drift. A reason is in the same comment after the directive and
its codes, in a second `#` segment, or in the own-line comment block directly above. Round 1 made
three things stricter: a bare Bandit code or test name after `nosec` (also `nosec: B603`) is not a
reason, a block above counts only when it names, on word boundaries, a rule code the directive
carries (`B603`, `SC2317`, `attr-defined`) or a tool (`bandit`, `shellcheck`, `mypy`, ...), or
opens a line with the project's `SECURITY:` marker (round 2 tightened this: the directive's own
words `no`, `cover`, `type`, `ignore` and substrings no longer count), and `init.sh`,
`venv.sh` and the two `nosec B603` lines now carry their own reasons. The test is still a word
match: a comment that names the tool but says nothing useful passes, and the generic-reason check
cannot tell whether a reason is true. It is registered as
`llm_qa.py inline_suppressions` and runs in `changed`. Reasons are inline and there is no
baseline file (owner ruling B2). The generic-reason check is `utils/escape_hatch.is_acceptable_reason`,
shared with the six `MUST_*_BECAUSE` hatches. Pinned by
`tests/unit/qa/test_check_inline_suppressions.py`, whose last test judges this repository.
Not done, on purpose: `--disable-nosem` and bandit `--ignore-nosec` would make the tools IGNORE
the kept directives, which contradicts B2 (they stay, with reasons); no `nosemgrep` exists today.
Not covered: `eslint-disable` (no `.ts` source), formatter markers.

**G6 closed for the identifiers; the fix text is reviewed, not enforced (Task 3.1b; review round
1 B1, B3).** `scripts/qa/qa-rules.json` (an entry per rule ID: statement, fix, printing scripts)
and `llm_qa.py --explain [ID]`, guarded in both directions by `tests/unit/qa/test_qa_rules.py`,
whose discovery now fails closed on an ID it cannot read; see 4.2. The six `shell-*` IDs that the
first version missed are registered and resolve. The accuracy of the `fix` and `statement` text
was checked entry by entry against each checker and corrected, once; 4.2d is graded PARTLY MET for
that reason. G6's listing half closed in Task 3.1e: the rules of three B checkers are
`batch-check` rows of `hooks-daemon defences` (see 4.2); the rest of B is not listed by the
coordinator's membership call, and the wrapped tools' own identifiers are theirs.

**G8 closed in part (Task 3.1b).** Phase 1 (first findings with IDs, absolute report path in
the summary) and phase 2 for three checkers (`check_magic_values.py`, `audit_error_hiding.py`,
`audit_shell.py` take `--path FILE`) are done; see 4.4 and D5.2/D5.3 under B. Review round 1
(S4) fixed the claim that the file is judged "as the tree run would": the two audit scripts now
refuse a file inside the repository that the tree run does not collect, as `check_magic_values.py`
already did. Task 3.1d added `check_british_english.py --path FILE` (same scope rules as the tree
run, one shared `out_of_scope_reason`). Not done: `--path FILE` on `check_module_length.py`
(report-only, so a one-file answer has no pass/fail to give); on the checkers whose `--path` already
takes a directory and writes a scoped artefact beside it (`check_python_var_guidance`,
`check_skip_list_substring`, `check_eacces_safe_predicates`, `check_authored_path_stat`,
`check_unreachable_handle_branch`, `check_inline_suppressions`, `check_sensitive_content`,
`check_skill_references`, `check_github_urls`, `check_daemon_dir_cd_in_docs`,
`check_install_mode_marker`, `check_released_changelog`: a file would change what the artefact
means, so each needs its own design); and on the cross-file or whole-tree checkers (inventories,
drift, doc-truth, handler-reference, hook-contract, repo-hygiene), where a single file is not the
unit. `llm_qa.py` itself has no file selection. Declared as a known gap (DETECTOR 5.2) in the declaration, Task 3.3.

**G7 closed (Task 3.1b; review round 1 S5).** See the 4.5 section: runners are registered and
resolved after every detector, and a runner that PASSED after a failed detector is marked
`NOT MEANINGFUL` and excluded from the pass count, while every tool still runs (Fable's
amendment). A runner that failed stays a failure and the exit code is non-zero.

**G4, G11, G12 status (Task 3.1c).**

- **G4 footer closed; the next-major requirement stays a declared known gap.** Every
  `To disable:` footer now reads `(set enabled: false and record why beside it)`, from one
  constant (`core/router.py:38`). The router's footer is the only one: five handlers printed
  their own as well (`write_clobber_guard`, `github_auto_close_keywords`, `git_message_backtick`,
  `error_hiding_blocker`, `security_antipattern`), so a deny showed two disable instructions;
  those lines are deleted and `tests/unit/core/test_single_disable_footer.py` pins it. Reasons stay optional and a
  reasonless entry under `daemon.strict_mode` stays a warning (owner ruling B3); the
  `exception_entries.py` docstring now says so. Making a reason mandatory is the breaking change
  for the next major and is not done here. `enabled: false` and `mode: warn` still have no
  reason field, so 6.2a stays NOT MET.
- **G11 `probe --only` closed.** `hooks-daemon probe <event> --only <handler>` sends
  `probe_only` (`daemon/hook_probe.py:247`); the chain consults only that handler
  (`core/chain.py:1100`) and only for a probe-class source (`daemon/synthetic_traffic.py:185`), so
  real traffic cannot switch guards off. The name is checked against the enabled handlers the
  project loads, bundled, project and plugin (`_loaded_handler_keys` in `daemon/cli.py`, checked in `cmd_probe`; the generator `defences`
  uses plus the project loader); a handler the event does not have, a non-probe source and a
  payload that contradicts `--only` are refused before anything is sent. `detector_entry_point`
  now names it (`rule_explain/defences.py:131`). The project-handler gap is closed (Task 3.1d): the
  docs generator still files a project handler under its class name and, when it cannot place it,
  under event `project`, but `cmd_defences` re-keys each project handler by the event and config key
  the project loader gives it (`_with_project_handler_keys`), so `defences` prints a working
  `--only` command for it. `tests/unit/daemon/test_cli_defences_project_handlers.py` feeds the
  printed value to the probe's own check. The `scan <handler> <paths>` mode and the next-major
  mandatory reason stay declared known gaps; no plan is to be filed for either.
- **G12 closed, and G3's listing half with it.** `hooks-daemon exceptions [--json]`
  (`cmd_exceptions` in `daemon/cli.py`) lists `exclude_paths` / `extra_whitelist` entries with their reasons
  (read from the raw config, since loading drops them), `enabled: false` and `mode: warn`
  handlers, `MUST_EXCEED_*_BECAUSE` declarations in tracked files, and the QA exception files.
  Limits, stated so they are not read as coverage: the in-file scan matches a token written as
  a comment opener plus the token, so a documentation code fence showing the hatch is listed too;
  inline `nosec` / `noqa` / `type: ignore` annotations are not listed, and neither are exemption
  constants hard-coded in scripts (for example `_EXEMPT_SUBPATHS` in
  `check_python_var_guidance.py`); the QA exception file set
  (`config/exceptions_listing.py:39`) has eight members, the six chosen from `scripts/qa` and
  `contracts/` plus `pyproject.toml` (ruff per-file-ignores, mypy exclude and overrides, deptry
  ignore) and `.pre-commit-config.yaml` (bandit `-s B101`), added on the coordinator's call. That
  membership is a coordinator call, not an owner ruling.

**G5, G9, G13, G15 status (Task 3.1a).** All four are closed except where noted.

- **G5 closed.** The five library handlers (`dispatch_declaration`, `subagent_report_size_blocker`,
  `subagent_report_path_verifier`, `cron_stop_enforcer`, `cron_subagent_stop_enforcer`) and the
  four project handlers (`ruff_format_blocker`, `enforce_llm_qa`,
  `plan_done_requires_holding_area`, `release_blocker`) now declare a `Rule` and print
  `BLOCKED [R-...]` on every deny path. `test_rule_parity.py` has no allowlist
  (`AutoApproveReadsHandler` declares `R-PERMISSION-REQUEST-NON-READ-TOOL` too) and holds the
  project handlers to the same rule. The parity test finds a denying handler by the
  `Decision.DENY` source marker, but the structural plugin
  (`tests/plugins/deny_carries_rule_id.py`) judges every deny any handler test provokes, so the
  headline claim does not rest on that marker.
- **G9 closed for the handler layer.** `hooks-daemon defences --json` fills `defect_class` on
  every row from the handler's own `defect_class` declaration, and lists only the handlers that
  declare one, which is owner ruling C1 (content and commit gates are the Defence set; action
  guards are guardrails). `defect_class` is the closed `DefectClass` enum, and
  `tests/unit/test_defence_membership.py` pins the set and checks each member blocks. `explain-rule` and `explain-handler` print the class, or a guardrail
  line, and `explain-rule --list` ends with a footer naming `explain-rule <ID>`. The three B
  batch checkers that mirror a handler are rows too (Task 3.1e, `kind: batch-check`).
- **G13 closed.** A promoted section ends with an `IDs:` line: 11 promoted sections, 25 IDs.
- **G15 closed.** `explain-rule plan-doc-size` prints the check's purpose and the umbrella
  rule(s) its denies are filed under; `test_rule_parity.py` walks every `CHECK_ID` constant in
  `plan_qa/checks/` and `docs_qa/checks/` and requires a `STATEMENT` constant beside each. The
  statement printed is that constant, so no second registry exists and no raw docstring markup
  reaches the output.
- **Defence membership rulings (coordinator, review round 1 S5; NOT the owner's).** These apply
  the DBF definition (a Defence finds a class of defect in content, and blocks) to the handlers
  C1 left open; the owner has not ruled on them and may overrule. `lint_on_edit` and
  `validate_eslint_on_write` are NOT Defences (they run after the write and only warn);
  `staged_lint_gate` is the Defence for the `lint-failure` class; `github_auto_close_keywords` IS
  a Defence (a content gate on commit messages, class `issue-closing-keyword`); `tdd_enforcement`
  is NOT (it guards an action, not content). The project handler
  `plan_done_requires_holding_area` is a Defence of its own class,
  `unrecorded-release-consequence`. `R-CONFLICT-MARKER-SCAN-TIMED-OUT` and
  `R-CONFLICT-MARKER-COMMIT` are two rows of one Defence (`conflict_marker_commit_gate`): the
  timed-out row is a fail-closed verdict of the same gate, not a second Defence.
- **`dispatch_declaration` row (N3), accepted.** `R-DISPATCH-DECLARATION-MISSING` is listed in
  the generated "All other enforced rules" table although the handler's default is advisory
  (`strict: false`). The row is an honest statement of what the rule does when a project turns
  strict on, the advisory pointer stays in the handler's own guidance, and the table cannot
  read per-project options.
- **Orchestrator rule (N4).** `R-ORCHESTRATOR-MAIN-THREAD-WRITE` now resolves in
  `explain-rule` in every mode: `orchestrator_simulate` declares the rule always, and the
  rule's own text says it fires only when blocking is armed. The lookup builds handlers
  without config, which is why the declaration cannot depend on the mode. The consequence,
  accepted knowingly like N3 (coordinator's ruling, not the owner's): in simulate mode
  `orchestrator_simulate` moves from the Advisories one-liner list into the rule table, where its
  row states the rule fires only when blocking is armed. The generator has no cheap way to keep
  the "SIMULATE ONLY" one-liner for a dormant rule.
- **DEFSET wording closed.** `DefenceBeforeFix.EXPLAIN_LINE` no longer calls every rule a
  defence, and README.md "Defence Before Fix" names the content and commit gates as the Defences.

### What a DBF tool needs in order to hook in (TOOLING §5, and Task 3.2)

The `/dbf` skill's discovery reads a manifest declaration first. Only `composer.json` and
`package.json` keys are defined (upstream #2). It then looks the toolchain up in
`register.json`, and otherwise falls back to the register without opening the project's own
detectors (upstream #4, draft
[01](../00467-recommend-the-defence-before-fix-plugin-to-client-projects/upstream-drafts/01-fallback-skips-project-detectors.md);
EVALUATION.md Criterion 1). To be discoverable without project-specific knowledge, the daemon
needs:

1. **A declaration in `pyproject.toml`**, for example under `[tool.defence-before-fix]`. It
   would carry `method`, `toolchain` and `known-gaps`, plus pointers to:

   - the listing command (`hooks-daemon defences --json`, a proposed name);
   - the resolver (`hooks-daemon explain-rule <ID>`);
   - the accept entry point (`scripts/qa/llm_qa.py all`, `changed` for subsets);
   - B's rule directory (`scripts/qa/`) and C's (`scripts/qa/semgrep/`).

   The key name needs agreement upstream: plugin #2 is open, so the plugin will not read it
   until then.

2. **A machine-readable listing (G9).** One row per active defence: identifier, handler or
   detector, terse statement, defect class (from `CLAUDE/Security/`), docs route and the entry
   point that runs it. It must be derived from the loaded config.

3. **For a client project**, the same declaration emitted by the installer into the client's
   manifest, or a documented path to the listing command. The artefact grade is what a
   client's DBF tool sees.

4. **The sweep route (G11).** Without it, a DBF tool can enumerate the daemon's content
   defences but cannot run them over existing code. It will then correctly choose a detector
   in B or C for the sweep, which is today's practice under `CLAUDE/Security/README.md`.

## Known gaps: draft text for the §9.2 declaration

This is the shape from DETECTOR-SPEC §8.1, with the two levels named separately (TOOLING §9.1).
Edit it after the owner's rulings in Task 2.3. Remove any gap the plan closes before Task 3.3
publishes.

```toml
[tool.defence-before-fix]
method = "1.0.1"

[tool.defence-before-fix.project]   # this repository's own assembled toolchain
toolchain = "0.2.0"
known-gaps = [
  "TOOLING 4.1: the scripts/qa checkers cannot run over a single file (DETECTOR 5.2), and the daemon prints no identifier on 9 deny paths (DETECTOR 4.3).",
  "TOOLING 4.2: identifiers printed by the scripts/qa checkers resolve to no documentation.",
  "TOOLING 4.3: inline suppressions (# nosec, nosemgrep, type: ignore, noqa, shellcheck disable) and the in-band MUST_*_BECAUSE overrides are honoured and not forbidden; the overrides are never written to the project record.",
  "TOOLING 4.4: llm_qa.py has no single-file subset and prints no identifiers in its own output.",
  "TOOLING 4.5: llm_qa.py runs the test suite before most detectors and does not stop on a detector failure.",
  "TOOLING 5.3: the scripts/qa checkers' rules and four project handlers' denials appear in no listing.",
  "TOOLING 6.2: no exception in .claude/hooks-daemon.yaml or the scripts/qa exception files must carry a justification, and generic justifications are not rejected.",
]
notes = [
  "ruff, pyright and shellcheck run as checks; no DBF Defence is routed through them (TOOLING 4.1 point 3).",
  "Hook-time defences are guardrails for a careless agent, not a guarantee against a hostile one: the hook layer fails open when the daemon does not answer (CLAUDE/ARCHITECTURE.md, Threat model).",
]

[tool.defence-before-fix.artefact]  # the daemon as installed into a consuming project
toolchain = "0.2.0"
known-gaps = [
  "TOOLING 4.1 / DETECTOR 4.3: five bundled handlers deny without printing an identifier.",
  "TOOLING 4.3: the in-band MUST_*_BECAUSE overrides bypass the project record, and MUST_SKIP_SAFE_MODE_BECAUSE requires no reason.",
  "TOOLING 5.1/5.2: no single listing of active defences carries identifiers; explain-rule --list is derived from installed code, not the active configuration.",
  "TOOLING 6.2: no exception in .claude/hooks-daemon.yaml carries a required justification.",
]
```

## Method notes

- **Run, all read-only or writing only to `untracked/scratch/`:**
  - `remote-docs check` and `remote-docs list`;
  - the plugin's `refresh-spec.bash --force` into a scratch cache;
  - `explain-rule --list` (121 rows), `explain-rule R-PIPE-TO-TAIL`, and
    `explain-rule R-ORCHESTRATOR-MAIN-THREAD-WRITE` (unknown, as intended);
  - `explain-handler --list`;
  - `probe PreToolUse --file` on a `git reset --hard` payload.
- **Not run:** `generate-docs` (it writes a tracked file) and the full `llm_qa.py` (the
  coordinator's gate).
- **Found by the ID comparison:** comparing the IDs in CLAUDE.md with `explain-rule --list`
  gave the 96 / 121 figure. Comparing literal IDs in source with the list gave the one
  intended exception.
- **Delegated inventories, spot-checked against the code:** the `MUST_*_BECAUSE` inventory, the
  scripts/qa detector survey and the config-exception survey came from three read-only Explore
  sub-agents. I checked `bash_safe_mode.py:260`, `git_stash.py:38-41`,
  `comment_size.py:104-130` and `verdict_log.py:96-126` against the code.
- **One sub-agent claim was refuted:** it said `docs_generator` mislists shipped-disabled
  handlers. Registration uses the same absent-key default (`registry.py:237`). The real
  divergence is the tag gates.
