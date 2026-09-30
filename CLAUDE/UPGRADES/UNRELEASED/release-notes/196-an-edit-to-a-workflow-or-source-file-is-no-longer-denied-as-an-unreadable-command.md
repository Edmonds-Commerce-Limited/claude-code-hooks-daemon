# Callout: an Edit of a workflow or source file is no longer denied as an unreadable shell command

**Plan**: 00474
**Audience**: operators

`secret_file_guard` denied an `Edit` of `.github/workflows/qa.yml` with
R-SECRET-COMMAND-UNREADABLE when the added text held a GitHub Actions
expression such as `name: QA (Python` followed by a doubled-brace matrix
reference. A workflow is not a command, and the expression is substituted by
the runner before any shell sees the step, but the guard read the whole added
text as shell and could not place the doubled braces. The same denial fell on
any `.py`, `.ts` or Makefile content whose text the shell reader could not
place. Only the added text (`new_string` or `content`) is judged; the
`old_string` of an Edit is never read.

For a CI workflow, expressions are neutralised first, so a `run:` step beside
one is still scanned as shell. Anything scanned as shell (`.sh`/`.bash`, shebang
scripts, Makefiles, CI YAML) that the reader still cannot place keeps failing
closed as unreadable: a Makefile recipe runs as shell and nothing else checks
it, and a literal re-scan cannot see a path assembled from variables. Only a
file not scanned as shell at all (`.py`, `.ts`, ...) is re-scanned literally:
a real mention of a protected path still denies, but the file is no longer
denied merely for being unparseable as shell. Nothing is excluded or
allow-listed.
