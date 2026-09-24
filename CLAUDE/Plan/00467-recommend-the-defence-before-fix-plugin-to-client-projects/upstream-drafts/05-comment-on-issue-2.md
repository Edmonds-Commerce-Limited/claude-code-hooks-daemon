# Draft: comment on Defence-Before-Fix/claude-plugin#2 (new evidence, not a new issue)

**Status**: draft, not posted. #2 is ours and still open, with no comments. Replace `#N` below
with draft 01's issue number once it is filed, or delete that paragraph if 01 is not filed.

## Comment

A data point from a real remediation run, following SKILL.md by hand in the same Python
repository.

The defect was in a Bash helper, not in Python: a watchdog that must survive a stripped `PATH`
ran `sleep` from `PATH`. So step 1 met both gaps together:

- No declaration was found, because `pyproject.toml` has no key (this issue).
- `register.json` has no shell row, so the green-first fallback lands on the Multi-language
  tools (ast-grep, pre-commit). Meanwhile the project already runs a Semgrep rule directory that
  picks up new rule files automatically, and a bespoke shell auditor. Both are natural homes for
  the rule, and step 1 would look at neither.

The class was real and worth the method. An independent search for "shell code that must
survive a hostile `PATH` but depends on a `PATH` command" found four more candidate instances
across three other scripts (unguarded `date` and `pgrep` lookups whose absence silently takes a
wrong branch).

The discovery-order half of this (SPEC section 2: check the detectors the project already runs
before choosing a new one) is filed separately as #N. A declared entry point, as this issue
proposes, would also have given the independent searcher its keep-out list. Today that list's
defaults are PHP and TypeScript paths only.
