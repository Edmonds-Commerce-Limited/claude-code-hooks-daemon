# Callout: a git failure at daemon start is reported as a git failure, not as an invalid configuration

**Plan**: 00474
**Audience**: client projects

When git failed at daemon start (for example `git rev-parse` exiting 128 because the installed git is too old for the repository's format), the daemon printed "Invalid configuration" and "Fix the configuration file and try again", and dropped git's own error. No edit of the configuration could fix it. The daemon now raises a dedicated error (a `ValueError`, so existing handling still works) that says which git step failed, its exit code and git's stderr, for three cases: `rev-parse` failed, there is no `origin` (or its URL is empty), or the toplevel could not be determined. The failure is logged at WARNING with git's stderr. The CLI start-up check names the project root and git, and suggests checking the repository or the git version. A genuinely invalid configuration still reports "Invalid configuration".
