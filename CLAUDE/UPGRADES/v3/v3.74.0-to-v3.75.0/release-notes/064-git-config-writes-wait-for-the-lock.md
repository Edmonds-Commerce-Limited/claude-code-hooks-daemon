# Callout: a branch park and the plan counter now wait for a held git config lock instead of failing at once

**Plan**: 00474
**Audience**: client projects

Git does not retry `.git/config.lock`, and every checkout and parallel agent of a repository shares that one config file, so a park record or the plan counter written while another git process held the lock failed immediately. `branch-park` (the park record and its clear) and the plan counter now wait for the lock for a few seconds, longer on a loaded host, and fail with an error that names the lock file when it stays held. A lock more than a minute old with no git process running is reported as stale, with the command to remove it; the daemon never deletes it for you.
