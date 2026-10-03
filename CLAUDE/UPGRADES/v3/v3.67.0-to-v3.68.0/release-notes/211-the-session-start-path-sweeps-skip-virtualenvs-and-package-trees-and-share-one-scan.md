# Callout: the SessionStart path sweeps skip virtualenvs and package trees and share one scan

**Plan**: 00474
**Audience**: operators

In a working copy that keeps many gitignored files (virtualenvs, copies of the repository under a scratch directory), `gitignore_safety_checker` and `secret_file_hygiene_checker` each spent about 35 seconds judging roughly 530,000 paths, which pushed the whole SessionStart chain past its 20 second budget. Now both sweeps share one scan and one set of protection verdicts per event, ignored files inside a virtualenv (a directory holding `pyvenv.cfg`) or a `node_modules` tree are no longer judged (they are not the project's files; tracked files there still are), and the check resolves each directory once and rules out most paths with a single substring test before any glob is tried. On a repository of that size the two sweeps together went from about 71 seconds to about 8 seconds. Which of the project's own protected files are reported is unchanged: a differential test compares the faster check with the per-path one on symlinks, loops, missing files and nested directories.
