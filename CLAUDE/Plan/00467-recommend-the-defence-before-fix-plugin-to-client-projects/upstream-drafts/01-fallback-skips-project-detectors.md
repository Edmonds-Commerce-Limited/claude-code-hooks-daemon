# Draft: step 1 picks a register tool before checking the detectors the project already runs

**Target**: `Defence-Before-Fix/claude-plugin`
**Status**: draft, not filed. Related to #2 (declaring a Python or bespoke entry point), but a
separate defect: this one is about the discovery order when nothing is declared.

## Title

Toolchain discovery falls back to the register before checking the project's existing
detectors, which SPEC section 2 requires

## Summary

`skills/dbf/SKILL.md` step 1 ends with:

> If the project has no toolchain graded in the register, choose a detector for the language
> from the register, preferring one graded green for detector conformance, and say in the report
> what the project's tooling lacks.

The method specification sets a different order. SPEC 1.0.1 section 2, last paragraph: the
attempt "is complete when the Practitioner has checked the Detectors the project already runs
and the language's own Detector ecosystem for an extension point, and found none."

So in a project whose detectors are not graded in the register (bespoke checkers, a project's
own Semgrep rule directory, a custom lint script), the skill goes straight to the register. It
never looks at what the project already runs. It then reports as missing a capability that the
project has.

A second gap makes this worse for shell. `register.json` has no row for shell or Bash. Its
`languages` are PHP, JavaScript and TypeScript, Python, Go, Rust and Multi-language. A defect in
a shell script therefore falls through to the Multi-language rows, and "preferring one graded
green" picks ast-grep or pre-commit. The project's own detector is never considered.

## Reproduction

1. Make a small Python project with:
   - a bespoke detector, `scripts/qa/check_example.py`, which scans files and exits 1 on a
     finding;
   - a Semgrep rule directory, `scripts/qa/semgrep/`, with one rule;
   - a single QA entry point that runs both, for example `make qa`;
   - a Bash helper script with a defect in it.
2. Do not add any declaration, because none is defined for `pyproject.toml` (see #2).
3. Run `/dbf` on the Bash defect.
4. Observe step 1. There is no declaration and no graded toolchain, so the skill reads
   `register.json`, finds no shell row, and proposes a Multi-language tool graded green
   (ast-grep). It does not open `scripts/qa/` or the entry point.

Without running anything, compare `skills/dbf/SKILL.md` lines 56-58 with SPEC section 2's last
paragraph. `python3 -c "import json; print(json.load(open('skills/dbf/references/spec/register.json'))['languages'])"`
shows that the register has no shell row.

## Suggested direction

- Add a step before the register fallback: "find the project's QA entry point (Makefile,
  `scripts/`, CI workflow, `pre-commit` config, task runner) and the detectors it already runs.
  Prefer an extension point in one of them (a rule directory, a plugin, a bespoke checker
  pattern) over introducing a new tool." Cite SPEC section 2.
- Let the independent searcher's keep-out list come from what that step finds. The defaults in
  `agents/independent-searcher.md` (`phpstan.neon`, `qaConfig/`, `eslint.config.*`, ...) are
  PHP and TypeScript only.
- In the site repository, not the plugin: consider a shell row in the register (ShellCheck,
  plus ast-grep and Semgrep, which already parse Bash).
