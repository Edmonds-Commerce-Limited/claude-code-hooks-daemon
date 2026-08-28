# QA

How quality assurance works in this repository, for humans. The canonical
in-depth reference is [CLAUDE/QA.md](../CLAUDE/QA.md) — full policy, all three
QA layers, and the acceptance-testing story live there.

## What the suite covers

The automated QA suite is a battery of deterministic checks: formatting
(Black), linting (Ruff), strict type checking (MyPy), the unit/integration
test suite with coverage, security scanning (Bandit, Semgrep), shell-script
linting, dependency-lock consistency, and a set of project-specific guards
(magic values, documentation truth, sensitive content, and others).

**The runner is the single source of truth for the exact list** — checks are
added over time, so don't trust any written enumeration. Read
`scripts/qa/run_all.sh` to see what runs today.

## Running it

From the project root:

```bash
./scripts/qa/run_all.sh        # the human entry point — verbose, colourised
```

AI agents use a different entry point — `./scripts/qa/llm_qa.py all` runs the
same suite with LLM-optimised output, and a project handler denies agents
invoking `run_all.sh` directly. If you're a human at a terminal, `run_all.sh`
is yours.

Individual checks exist as sibling scripts following the same pattern
(`scripts/qa/run_lint.sh`, `run_type_check.sh`, `run_tests.sh`, …), and
`./scripts/qa/run_autofix.sh` applies Black and Ruff fixes automatically.
Machine-readable JSON results land in `untracked/qa/` (gitignored).

## The hard requirements

- **Every check must pass** before a commit — there is no partial credit.
- **Test coverage**: 95% minimum.
- **Security findings**: zero, at every severity (only assert-statement
  warnings are filtered).

Full policy, rationale, and the deeper QA layers (sub-agent review,
acceptance testing) are in [CLAUDE/QA.md](../CLAUDE/QA.md). Common failure
patterns and their proper fixes are catalogued in
[CLAUDE/development/QA.md](../CLAUDE/development/QA.md).

## The client-project QA runner (separate thing)

Distinct from the repository's own QA suite, the daemon ships a small QA
runner module (`src/claude_code_hooks_daemon/qa/`) for running checks like
ESLint, TypeScript, Prettier, and CSpell against a *client* project, with
structured JSON output. Invoke it through the wrapper (which resolves the
daemon's virtualenv for you):

```bash
./scripts/run-qa-runner.sh <project-root> "eslint,typescript"
```

Its technical documentation lives with the module in
`src/claude_code_hooks_daemon/qa/CLAUDE.md`.
