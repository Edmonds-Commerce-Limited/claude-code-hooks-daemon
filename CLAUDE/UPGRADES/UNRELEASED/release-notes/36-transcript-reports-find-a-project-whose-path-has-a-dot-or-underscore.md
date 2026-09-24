# Callout: transcript reports find a project whose path has a dot or an underscore

**Plan**: 00466 (N27)
**Audience**: everyone whose project path contains `.`, `_`, a space or any other character outside `a-z`, `A-Z`, `0-9`

Claude Code keeps each project's transcripts in a directory named after the
project path. Every character outside `a-z`, `A-Z` and `0-9` becomes `-`. A
name longer than 200 characters is cut and given a hash suffix.

`skill-scan` and `cache-gaps` replaced only `/`, so for a path such as
`/srv/my_app.v2` they looked in a directory that does not exist and found no
prompts. `tool-report` and `block-report` were right, except for paths over
200 characters. All four now use one helper that follows Claude Code's rule
exactly, including the long-path hash.

When the derived directory does not exist:

- `cache-gaps` says which directory it looked in;
- `tool-report` and `block-report` name it on stderr, then still report.
