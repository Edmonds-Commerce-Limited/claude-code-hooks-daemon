# Callout: an empty path candidate no longer crashes the secret-path guards

**Plan**: 00466
**Audience**: operators

A Bash command as ordinary as `cp ~/ /tmp/x` could crash the secret-path
Bash-mention scanner: the bare `~/` token strips to an empty string, and that
empty candidate reached `os.path.relpath("", project_root)`, which raises
`ValueError: no path specified` instead of answering "no match". The
handler's exception was swallowed upstream, so the Edit or Bash command it
was judging went through unblocked -- a silent fail-open, not just a crash.
`path_exclusion.path_matches_globs` and `path_segments.matches_path_segment`,
the shared chokepoints every content-guard handler funnels a candidate path
through, now treat an empty candidate the same way they already treat one
that resolves outside the project root: no match, never a raise.
