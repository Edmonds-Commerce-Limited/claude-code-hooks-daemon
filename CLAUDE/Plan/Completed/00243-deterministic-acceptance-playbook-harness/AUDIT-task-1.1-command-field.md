# Task 1.1 — audit of every `get_acceptance_tests()` `command` field

Read-only audit, 26-08-21. Counts came from running the real generator
(`bin/hooks-daemon generate-playbook --format json`) and cross-checking against
an AST sweep, not from grepping. `--include-disabled` yields the same totals,
so nothing is currently config-hidden.

This is the measurement every later task in the plan depends on. It replaces
"17 tasks of unknown size" with a costed work-list.

## Totals

| Measure                                             | Count |
| --------------------------------------------------- | ----- |
| `get_acceptance_tests()` in `handlers/`             | 84    |
| …in `.claude/project-handlers/`                     | 2     |
| …in `strategies/` (delegated-to, load-bearing)      | 75    |
| **Total implementations**                           | 161   |
| `AcceptanceTest` objects the generator emits        | 219   |
| `CliAcceptanceTest` objects (a different dataclass) | 3     |
| **Total playbook blocks**                           | 222   |

Five handlers declare ZERO tests directly and inherit all of theirs from
strategies — `post_tool_use/lint_on_edit.py:384`,
`pre_tool_use/error_hiding_blocker.py:185`, `pre_tool_use/qa_suppression.py:242`,
`pre_tool_use/security_antipattern.py:162`,
`pre_tool_use/tdd_enforcement.py:529`. **A converter written per-handler will
miss them**: the strings live in the 75 strategy files.

## The three buckets

| Bucket                                    | Count | %   |
| ----------------------------------------- | ----- | --- |
| (a) literal shell, runnable via `bash -c` | 98    | 45% |
| (b) prose, mechanically convertible       | 115   | 53% |
| (c) genuinely not executable              | 6     | 3%  |

Two caveats that stop the headline being read as 97%:

- **35 of the 98 in (a) are vacuous.** They are `echo "test"` fired at a
  SessionStart / StatusLine / PreCompact handler that does not respond to a
  Bash `PreToolUse` at all, asserting `['.*']` or `[]`. They execute, they
  pass, and they test nothing.
- **~30 of the 115 in (b) DESCRIBE their payload** rather than stating it
  ("whose content has a trailing `#` comment reading changelog-style
  history"). Those need a structured payload field, not a parser.

## Bucket (b) shapes — five grammars, one payload

| Shape                                                        | Count |
| ------------------------------------------------------------ | ----- |
| `Use the Write tool to create file <path> with content "…"`  | 30    |
| `Use the Write tool to create <path> whose content has …`    | 16    |
| `Use the Write tool to write file_path='…' with content '…'` | 13    |
| `Write file_path="…" content="…"` (bare kwargs)              | 13    |
| `Write(\n file_path='…',\n content='…'\n)` (Python call)     | 10    |
| `Use the Write tool to write to <path> with content '…'`     | 10    |
| `Use the <OtherTool> tool with <args>`                       | 9     |
| `Use the Write tool to create <descriptive target>`          | 7     |
| `AskUserQuestion call where <described payload>`             | 3     |
| `Use the Edit tool on <path> with old_string … new_string …` | 2     |
| one-offs                                                     | 2     |

**Shapes 1, 3, 4, 5 and 6 are the same semantic payload written five different
ways — 76 tests, five grammars, one target.** That is where the plan's measured
"49 false failures" came from, and normalising it is Task 1.2's whole job.

Shapes 2, 8 and 9 (26 tests) plus two placeholders in shape 7 are NOT
parseable: the content is described in English. Those are Task 1.3's structured
field.

## Bucket (c) — the SKIPPED-with-reason list, in full

| Handler                        | file:line                                               | Why it cannot be executed                                                                                                   |
| ------------------------------ | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `AutoApproveReadsHandler`      | `handlers/permission_request/auto_approve_reads.py:122` | Needs a `PermissionRequest` event AND session-level `permission_mode=bypassPermissions`; the mode cannot be set mid-session |
| `AutoApproveReadsHandler`      | `handlers/permission_request/auto_approve_reads.py:137` | Same event with `permission_mode=default`; asserts the daemon DEFERS — an absence of action, unobservable from a wrapper    |
| `AbsolutePathHandler`          | `handlers/pre_tool_use/absolute_path.py:133`            | Claude Code normalises a relative `Read` path to absolute before the daemon sees it, so the deny is unreachable             |
| `AbsolutePathHandler`          | `handlers/pre_tool_use/absolute_path.py:148`            | Same normalisation, `Write` variant                                                                                         |
| `PlanQaCommitGateHandler`      | `handlers/pre_tool_use/plan_qa_commit_gate.py:275`      | Needs a STAGED PLAN.md status flip in the live repo plus a real `git commit`, asserted on main-thread context               |
| `AgentIsolationAdvisorHandler` | `handlers/pre_tool_use/agent_isolation_advisor.py:149`  | Silent unless `_count_live_threads() >= 2` — daemon-side registry state fed by status-line heartbeats, not by any payload   |

**Borderline, flagged for the plan to rule on rather than decided here:**

- `SensitiveContentHandler` (`pre_tool_use/sensitive_content.py:465,483,510,530`)
  — constructible, but needs `public_patterns` configured or
  `secret_word_list_path` repointed at a throwaway file, plus a daemon restart
  and a restore. Whether config-mutation belongs in harness setup is a
  decision, not a fact. Note the real `.claude/block-words.secret` exists here
  (mode 0600), so reading a term at harness time is possible but would write a
  real secret into probe input — do not.
- `WriteClobberGuardHandler` (#66) — executable, but only because its
  precondition is the ABSENCE of state: a fresh synthetic `session_id`
  satisfies "a file you have NOT read in this session" by default. Recorded so
  nobody later "fixes" it into a real setup step.
- `AgentIsolationAdvisorHandler` #195 IS executable
  (`isolation: "worktree"` is a plain payload). Only #194 needs the registry.

## Defects this audit surfaced

These are live bugs, not plan-sizing data:

1. **Project-handler tests never reach any playbook.**
   `cmd_generate_playbook` (`daemon/cli.py:2250-2256`) never passes
   `project_handlers=`, so `PlaybookGenerator._collect_tests`'s project-handler
   branch (`playbook_generator.py:280-311`) is dead on the CLI path. Three
   declared tests are silently absent from the release gate.

2. **`generate_json` does not emit `harness_cannot_produce`**
   (`playbook_generator.py:391-413`). Only the markdown renderer shows the SKIP
   marker, so a JSON-driven harness cannot see it. Blocks Task 2.2.

3. **`SedBlockerHandler` test #22** (`pre_tool_use/sed_blocker.py:451`) — its
   `command` is `/workspace/untracked/test_sed_acceptance.sh`, a FILE PATH, not
   a command; the real instruction is buried in `description`. It declares
   `expected_decision=DENY` but as written cannot produce one. This is the most
   dangerous shape in the set: it LOOKS like bucket (a) and silently is not.

   **The hardcoded root turned out to be a CLASS, not this one test.** Fixing it
   raised the obvious question of how many others name `/workspace`, which is
   real in self-install mode and false in every client install — a shipped test
   telling a client-install tester to WRITE to a path outside their project.
   Grepping the handlers package found 4. Collecting through the real generator
   with `ProjectContext` initialised found **17**: the 13 the grep could not see
   live in `strategies/security/*.py`, reached only via the five handlers that
   delegate their whole test set, and two more only appear once handler
   construction succeeds. The hand-search undercounted by a factor of four.

   The guard for this already existed and did not cover this surface.
   `tests/integration/test_generated_docs_are_path_agnostic.py` (Plan 00244)
   asserts exactly this property for `get_claude_md()` and for the generated
   `.claude/HOOKS-DAEMON.md` — two of the three artifacts rendered from handler
   code. `get_acceptance_tests()` feeds the third, the playbook, and was never
   checked. It is now covered there rather than in a rival file, so the property
   has one home.

4. ~~**`PlanNumberHelperHandler` #165** — answered by `pipe_blocker` (17)
   before `plan_number_helper` (33), so it passes for the wrong reason.~~
   **REFUTED.** The audit marked this "verify, not confirmed" and the
   verification contradicts it. All four of this handler's tests were driven
   through the production forwarder against the live daemon:

   | Test command                         | Expected | Live verdict | Patterns   |
   | ------------------------------------ | -------- | ------------ | ---------- |
   | `ls -d …/0* … \| sort -V \| tail -1` | deny     | **deny**     | both match |
   | `mkdir -p …/99999-acceptance-probe`  | deny     | **deny**     | matches    |
   | `mkdir -p …/Completed`               | allow    | **allow**    | n/a        |
   | `find … \| wc -l`                    | allow    | **allow**    | n/a        |

   `pipe_blocker` never fires: `sort` is whitelisted, so the `| tail -1` pipe
   is allowed through and `plan_number_helper` answers with its own reason,
   which contains both declared patterns. Nothing to fix — recorded because a
   plausible unverified claim that survives into a plan becomes work someone
   later does for no reason.

## Assertion quality

- No test can be missing a required field: all five are non-default dataclass
  fields and `__post_init__` (`core/acceptance_test.py:141-148`) rejects an
  empty `title`/`command`/`description`. A missing one is a `TypeError` at
  import.
- `expected_message_patterns` has NO validation. **40 tests declare `[]`** (all
  ALLOW cases — correct) and **21 declare `['.*']`** (all CONTEXT probes —
  these assert nothing and will pass unconditionally under Task 2.3).

## The marker field already exists

`harness_cannot_produce: str | None` (`core/acceptance_test.py:139`), rendered
as a SKIP block by `_skip_block` (`playbook_generator.py:43-77`). Only **2 of
219** tests set it, both in `AbsolutePathHandler`.

Its docstring is deliberately narrow — "use ONLY when the harness rewrites or
intercepts the input… never to excuse a test that is merely awkward" — so it is
the WRONG field for "this command string is prose". Task 1.3's instinct is
correct: a second, distinct structured `tool` + `payload` field is needed, not
a widening of this one. `AcceptanceTest` has no slot for a tool payload today;
`command: str` is the only one.

## Bottom line

Of 219 handler tests, 98 are already literal shell and 115 are one
normalisation pass away, so ~183 (84%) could in principle reach a harness. That
headline overstates it twice: 35 of the 98 are vacuous `echo` probes, and ~30
of the 115 describe their payload in English.

**The honest figure is ~148 of 219 (68%) reaching a genuinely assertive
deterministic run** — 63 real shell tests plus ~85 fully-literal prose tests.

The conversion cost is small and concentrated: five string grammars cover 76 of
the prose tests, all expressing the identical Write payload. And the true
residual is tiny — **6 tests genuinely need a human in a real session**, which
turns Step 12's manual gate from ~169 items into six.
