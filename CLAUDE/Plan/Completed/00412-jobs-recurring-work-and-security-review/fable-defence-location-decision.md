# Decision: where a Defence lives — the ruling

Closes [DECISION-where-a-defence-lives.md](DECISION-where-a-defence-lives.md).
Decision only — nothing here was implemented, and the implementation it makes
necessary is listed at the end as unbuilt work.

## The ruling

**DECISION: option A is endorsed in direction and corrected in letter. Every
Defence is a Detector in `scripts/qa/`. That is not this repository's
preference to amend — it is a MUST of the method the owner adopted (Defence
Before Fix, method specification clause 3.2), so option B is not available as a
rule change, and option D is the silence clause 9.2 of the toolchain
specification forbids. But Rule A names the wrong artefact as the thing that
makes a Detector binding. `run_all.sh` is neither the invocation this project
uses to accept changes nor what CI runs. A Detector is BINDING when it has a
`TOOL_REGISTRY` entry in `llm_qa.py`, when its pytest wrapper asserts against
the real tree so that `pytest tests/` — the CI gate — fails when the rule
fires, and when one generic wiring test pins both of those and the `run_all.sh`
step for every `check_*.py`. Rule B's mechanism claim is true and becomes that
requirement; its conclusion is what clause 3.2 forbids; its citation is wrong.**

The document's argument for A holds. Its reasoning about WHY the wiring test is
needed does not: the failure it cites was a reporting defect, not a gating one,
and a wiring test does not address it. The reason a wiring obligation is needed
is different and stronger — one of the register's four rows is not enforced in
CI today, and Rule A's letter is satisfied by it.

## Evidence

### The document's factual claims, checked by reading

- "Class 15's Defence gates the build via `llm_qa.py`'s `tests` step" — TRUE.
  `_run_tools` returns `EXIT_FAILURE` when any tool fails (`llm_qa.py:957-984`),
  and `run_tests.sh` publishes `summary.passed_all`, which `_is_passed` reads
  first (`llm_qa.py:807-813`).
- "It is deliberately NOT in the register table" — TRUE. `CLAUDE/Security/README.md`
  carries four rows; class 15 is not one.
- "Its sibling is also a test and the two share `tests/subprocess_ast.py`" —
  TRUE (`test_git_spawns_are_bounded.py:48`,
  `test_subprocess_spawns_are_bounded.py:36`).
- "The shared AST module moves so `scripts/qa/` can import it" — TRUE as a
  cost. `pyproject.toml:103` sets `testpaths = ["tests"]`; a script run as
  `python scripts/qa/x.py` has `scripts/qa` on `sys.path`, not the repository
  root, so `tests.subprocess_ast` resolves under pytest only.
- "Rule B cites a REAL failure: a checker that ran, produced a verdict, and
  gated nothing because no consumer read its key" — **HALF WRONG.** The failure
  is real, recorded at `CLAUDE/development/LESSONS.md:106-130`. It is not Plan
  00244's and it did not gate nothing. The checker was
  `check_project_handler_tests.py` (added at `2318e88c`; the lesson was recorded
  at `4572abf8`, "from the release_blocker fix"). Plan 00244 is the
  path-agnostic generated-docs plan; it added no checker. And LESSONS.md:117 is
  explicit: "The check's exit code was correct throughout; only the line a human
  or an agent actually reads was wrong." The gate held. The summary LINE lied.
  The same misattribution stands in `test_git_spawns_are_bounded.py:16-19`,
  `test_subprocess_spawns_are_bounded.py:25-27` and `llm_qa.py:609`. This
  matters to the ruling because a reporting defect is answered by the reporting
  layer — the exit-code cross-check at `llm_qa.py:859-865` and class 5's shared
  renderer at `llm_qa.py:603-616` already do that — and a wiring test would not
  have caught it.
- "It further asserts that both existing categories honour this" — stale (the
  README now says four) and not quite true of the four, for the reason under
  point 3 below.
- "Sixteen classes remain" and the "Current state" section — stale. Since the
  document was written, classes 3, 5, 7, 9 and 10 landed as tests
  (`test_path_mutated_execution_resolves_argv_by_name.py`,
  `test_qa_checks_report_their_denominator.py`,
  `test_argv_is_not_built_by_splitting.py`,
  `test_git_enumerated_content_consults_protected_set.py`, and additions inside
  `test_sensitive_content.py`); class 2 landed as a handler pair
  (`guard_config_drift` at SessionStart, `guard_config_commit_gate` at
  PreToolUse, reporting); class 14 landed as a `scripts/qa/` Detector (check
  29, `check_security_downgrade_flags.py`) with no register row or page. Seven
  classes are untouched: 8, 11, 12, 13, 16, 17, 18. The corpus the document
  feared would split is already split three ways.

### What Rule A's letter anchors to, and what actually binds

1. **`run_all.sh` is the human path, not the entry point.** `CLAUDE/QA.md:33-35`:
   agents MUST use `llm_qa.py all`, and the `enforce_llm_qa` project handler
   denies `run_all.sh` to an agent. `RELEASING.md:490`, `:784` and `:972` name
   `llm_qa.py all` as the release gate. The method's clause 3.5 demands
   enforcement be shown through "the invocation the project uses to accept
   changes" (`SPEC.md:753-758`). Here that invocation is `llm_qa.py all`.
2. **`run_all.sh` and `TOOL_REGISTRY` have already diverged.** Six tools exist
   in `llm_qa.py` only — `github_urls`, `python_var_guidance`, `eacces_safe`,
   `plan_qa`, `docs_qa`, `smoke_test` — while `QA.md:39` calls `run_all.sh`
   "the single source of truth for which checks exist". Nothing tests parity.
   That is a documentation-truth defect outside this decision, recorded here
   because it is the measured proof that "wired into `run_all.sh`" and "runs at
   the gate" are different facts.
3. **CI runs no `scripts/qa/` Detector.** `.github/workflows/qa.yml:120` says
   the tools are invoked directly, and the steps are black, ruff, mypy,
   `run_pyright_check.py`, `pytest tests/`, `pytest .claude/project-handlers`,
   bandit, deptry, shellcheck and a handler-import probe. Not one `check_*.py`.
   So a register Detector reaches CI only through a pytest wrapper that asserts
   against the real tree. Four of the five `scripts/qa/` Detectors have one
   (`test_declared_invariant_pairs_checker.py:757-788`,
   `test_dangerous_invocation_corpus_checker.py:186-192`,
   `test_fail_open_inventory_checker.py:418-433`,
   `test_security_downgrade_flag_checker.py:555-561`).
   **`check_authored_path_stat.py` — check 25, the register's first row — has
   none**: its wrapper drives fixtures only. Register row 1 satisfies Rule A's
   letter and is not run in CI. That is the concrete case where the letter and
   the property have come apart, and it is the reason a wiring obligation is
   needed — not the misattributed 00244 story.
4. **The wiring-test pattern already exists and none of the five uses it.**
   `test_handler_reference_check.py:357-378` pins both the `TOOL_REGISTRY` entry
   and the `run_all.sh` step for its check. No register Detector has the
   equivalent, and `README.md:100` says so: "Nothing yet enforces that the NEXT
   one will."

### Why option B is not available — the method this project adopted

`CLAUDE/CodeLifecycle/Bugs.md:18-23`: "This project follows the method as
written there; nothing below replaces it." `DESIGN.md` Q3 records the owner's
decision to declare conformance with a clause 9.2 known-gap record.

The method's clause 3.2 (`SPEC.md:433-438`): "The Practitioner MUST express the
Class as a Rule in a Detector, and the Detector MUST read code rather than
execute it. A test MUST NOT serve as the Detector." The distinction it draws
(`SPEC.md:98-105`) is Detector — reads the text of the code, everywhere it
exists — against Runner — executes code and reports what happened, on the
paths exercised; a test Runner is its first example.

A pytest module that AST-walks `src/` reads code and does not execute it. In
SUBSTANCE it is a bespoke Detector, and the spec says custom AST walkers
qualify (`SPEC.md:446-448`). But the spec also says every clause applies to a
bespoke Detector "unchanged" (`SPEC.md:453-456`), and hosted in the Runner the
module fails the ones that make a Detector usable: it prints no stable
Identifier with each finding (method 3.6; detector specification 4.3), it
cannot be invoked over a subset or a single file (detector specification 5.2),
it has no harness distinct from the test suite (4.2 — "without executing the
project's own test suite"), and it runs at the Runner level, after the
Detectors, which the toolchain specification's clause 4.5 forbids for the entry
point. This project's own toolchain is built on the first two: `explain-rule`
resolves printed identifiers offline (DESIGN.md Q3 cites it against clause
4.2), and `qa_suppression` forbids the suppression route (clause 4.3). A
test-hosted rule sits outside both.

So "amend Rule A to permit a test as a Defence" would record a known
non-conformance as policy. Clause 9.2 says a MUST the project fails is
recorded as a gap alongside the declaration, not adopted as a rule. That is the
determinate answer to B, and it is a reading of the specification the owner
adopted rather than a preference about tidiness.

### Why option D is not available either

Clause 9.2 (`TOOLING-SPEC.md:446-449`): a project that has learnt it fails a
MUST "MUST record that gap alongside the version, in the same file or one it
names." Leaving six test-shaped Defences off the register is the silence that
clause forbids. The register's own text already takes the position from the
other side (`README.md:114-117`): "a register that only recorded what its
Detectors cover would describe the detectors, not the defects." A row whose
Defence cell names the test and states "interim — a Runner-hosted rule,
non-conforming to method 3.2, Detector owed" records a gap. It does not
overstate coverage, because it states the mechanism; overstating is what a row
that names a test as if it were a Detector would do, and that is the row the
document rightly refused to write.

### Rule B, resolved

Its mechanism claim is true and verified: a test module is collected by
`llm_qa.py`'s `tests` step and by `qa.yml:285` by construction, and pytest's
exit code is its verdict. Its cited failure is real, misattributed, and a
reporting defect rather than a gating one. Its conclusion — therefore a test —
is what clause 3.2 forbids. What survives is exactly what the document
proposed: the concern becomes a requirement. Corrected for what actually binds
in this repository, the requirement is the three-part binding in the ruling,
not a test asserting a `run_all.sh` step.

## What this decides for the classes, concretely

- **The seven unbuilt classes (8, 11, 12, 13, 16, 17, 18).** Each lands as
  `scripts/qa/check_<class>.py`, with an inventory or corpus YAML beside it
  where the class is inventory-shaped (the form classes 4, 6 and 14 took); a
  stable rule identifier printed with every finding; a `TOOL_REGISTRY` entry
  and summariser in `llm_qa.py`; a `run_all.sh` step; a
  `tests/unit/scripts/test_<name>_checker.py` carrying the harness fixtures AND
  a real-tree assertion; a `CLAUDE/Security/<Category>.md` page and a register
  row. No new test-shaped Defence lands from here.
- **The six test-shaped Defences (3, 5, 7, 9, 10, 15) and the Plan 00246 git
  guard.** They migrate to `scripts/qa/` as ONE worklist unit, not per class,
  because several share resolvers: 15 and the git guard move together with
  `tests/subprocess_ast.py`, which relocates to `scripts/qa/` (precedent:
  `contract_allowlist.py` is already a shared module there). The rule logic
  moves; the fixture tests stay as each Detector's wrapper and gain the
  real-tree assertion. Until a class migrates, it gets a register row that
  names the test and records the interim state as a 3.2 gap. No enforcement is
  lost in the interval — the tests keep running until the Detector replaces
  them.
- **Class 14.** Check 29 exists, conforms in form, and has no register page or
  row. The register under-reports a conforming Detector today. Page and row
  are owed.
- **Class 2.** Handler-hosted and reporting (`guard_config_drift`,
  `guard_config_commit_gate`). A handler is neither a Detector nor a test; it
  fires at session start and at commit, not at the QA entry point. It takes the
  same interim-row treatment. Whether its comparator should also be driven as a
  `scripts/qa/` Detector over the committed config is a question for when its
  owner-gated fix shape is decided, and is not ruled on here.
- **`authored-path-resolution` (check 25).** Its wrapper is owed a real-tree
  assertion. It is the only register row not enforced in CI.
- **Once, not per Defence: a generic wiring test** asserting that every
  `scripts/qa/check_*.py` has a `TOOL_REGISTRY` entry and a `run_all.sh` step.
  It replaces per-Detector wiring tests. Measured against today's tree it goes
  red on `check_github_urls.py`, `check_python_var_guidance.py` and
  `check_eacces_safe_predicates.py`, all registered in `llm_qa.py` and absent
  from `run_all.sh`. That is a finding the test is for, not a reason to narrow
  it.
- **The two rules' text.** `CLAUDE/Security/README.md:89-98`,
  `Routine/00001-security-review-full/ROUTINE.md:102-103` and PLAN.md Task 3.4
  reword "wired into `run_all.sh`" to the three-part binding. The Plan 00244
  attribution in the two guard docstrings and `llm_qa.py:609` is corrected
  when those modules are next touched.

Every item above is unbuilt. Nothing in this document changed code, and the
tree was frozen for a QA run while it was written.

## What it costs, and who bears it

- **Migration of seven Runner-hosted rules**, not the two the document costed.
  Each needs an identifier, a JSON report shape, a summariser, a registry entry
  and a step. The plan bears it, and it is mechanical: the detection logic does
  not change, which is the document's own observation about option A's risk.
- **Per new Detector, the existing pattern.** Classes 4, 6 and 14 already
  followed this shape end to end, so the cost of the ruling for an unbuilt
  class is the cost those three already paid.
- **A step list that must keep being maintained.** `run_all.sh` stays a
  hand-edited list of steps. The generic wiring test converts that maintenance
  from a silent gap into a failing check, which is the only way this repository
  has ever kept such a list honest (`llm_qa.py:414-417` records the last time
  two verbs shipped unregistered).
- **Nothing is lost in the interval.** Every test-shaped Defence keeps gating
  `llm_qa.py all` and CI exactly as it does today until its Detector lands.

## The strongest argument against, stated fairly

Rule B is right that a `scripts/qa/` Detector has more ways to go quietly
unbound than a test does: a registry entry forgotten, a summariser missing, a
wrapper with no real-tree assertion — check 25 is the live instance — and a CI
that never runs the script. A test has one way to run, and it is the way CI
runs. Choosing the form with more failure modes on the strength of a
specification clause can be read as conformance over protection, and the
person who wrote Rule B had just watched a freshly-added checker mislead its
readers.

The rebuttal is in two parts. First, each of those failure modes is pinned by a
test that exists or is one small file away, and the ruling requires them; the
form with more failure modes is also the form whose failure modes are all
testable, where a Runner-hosted rule's defects — no identifier, no subset
invocation, wrong level — are structural and cannot be tested away. Second,
the 3.2 distinction is not ceremony in this repository: a Detector prints an
identifier `explain-rule` resolves, runs over a single file when an agent is
mid-edit, and runs before the Runners so a class-level failure is named before
its symptoms. A pytest module does none of those, and the register's promise —
"a reader can trust what it says is covered" — is a promise about the class
being watched at the entry point, which a test-hosted rule keeps only for
whoever runs the whole suite.

## Human gate?

**None on location.** The owner adopted the method (DESIGN.md Q3; PLAN.md Task
3.4's own wording forbids the test from being the Detector), and clauses 3.2
and 9.2 decide the question between them. What remained open was whether Rule
A's letter named the artefact that actually binds, and that is a reading of
`qa.yml`, `llm_qa.py` and `run_all.sh` rather than a judgement about risk. No
installing project's refusal surface changes: this decision adds QA checks to
this repository and moves rule logic between files. Every per-class FIX that
the sibling decisions hold owner-gated stays owner-gated; this ruling says
where each class's Detector lives, and nothing about what its fix should be.

## One footnote, not a third option

The document's "What I did in the meantime" chose under-reporting as "the
recoverable direction". It was the right call for the day it was made, because
the alternative on the table was a row that named a test as if it met the
obligation. The interim row this ruling prescribes is a third shape the
document did not consider — a row that records the gap in the mechanism column
— and it is the shape clause 9.2 requires. It is not an option between A and
B; it is what A looks like while the migration is in flight.
