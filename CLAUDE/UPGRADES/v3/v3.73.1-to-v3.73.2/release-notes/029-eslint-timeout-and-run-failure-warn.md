# Callout: validate_eslint_on_write warns instead of denying when ESLint cannot run

**Plan**: 00478
**Audience**: client projects

Under the owner's "warn dont block" ruling, `validate_eslint_on_write` no longer denies when it has no verdict. If ESLint does not finish within its timeout (`R-ESLINT-TIMEOUT`) or cannot be launched (`R-ESLINT-RUN-FAILURE`), the write is now allowed with an advisory that says plainly the file was NOT linted, and one log line starting `UNKNOWN-VERDICT validate_eslint_on_write` is written. Both rule IDs stay, as advisory-only rules, so `explain-rule` and the advisory still cite them. ESLint errors that were actually reported still deny (`R-ESLINT-ERRORS`). A TypeScript file written while ESLint is hung or missing is therefore no longer stopped: run ESLint by hand when you see the advisory.
