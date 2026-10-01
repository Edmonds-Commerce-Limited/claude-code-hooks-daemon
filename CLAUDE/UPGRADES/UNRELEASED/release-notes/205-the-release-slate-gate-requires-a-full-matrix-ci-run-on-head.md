# Callout: the release slate gate requires a full three-Python matrix CI run on HEAD

**Plan**: 00475
**Audience**: operators

CI now runs only the tier a push needs, and a docs or code tier succeeds without running the three-Python matrix. `bin/hooks-daemon release-slate-check` therefore no longer accepts any green `qa.yml` run on HEAD: it reads the run's jobs and requires every `QA (Python3.x)` matrix job to have concluded success. A HEAD with only a tier green reports that, and the remedy is `gh workflow run qa.yml --ref main` (a manual dispatch runs the full tier), then waiting for it. If `gh` fails or its output cannot be read, the check exits 1 rather than reading the state as green.
