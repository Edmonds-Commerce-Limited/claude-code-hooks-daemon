# Callout: the secret-file guard closes a `git rm --cached` disclosure route

**Plan**: 00311
**Audience**: everyone

`git rm --cached --pathspec-from-file=<protected file>` made git echo the
protected file's lines back in its own error text, so the hygiene exemption
for `git rm --cached` no longer applies when that flag is present. The
exemption now also skips any leading global git flag (`-C`, `-c`), and a
one-line `python -c "import <module>"` is no longer denied for naming the
guard's own module. Separately, the dispatch-declaration advisory now honours
a non-default `plans_directory`, so a project with its own plan folder can
satisfy it.
