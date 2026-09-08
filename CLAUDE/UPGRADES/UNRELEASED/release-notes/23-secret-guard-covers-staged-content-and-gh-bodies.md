# Callout: the secret-term guard now covers staged content and `gh` bodies

**Plan**: 00362
**Audience**: everyone

`sensitive_content` gained two surfaces. A `git commit` is now denied when the
ADDED lines of any staged file (the working tree for `-a`) carry a secret-list
term or a public pattern, so a file that arrived by `mv`, `cp` or a shell
redirect can no longer reach history unexamined — the deny names only the file
path and the entry index, never the line, and a binary or oversized file is
stood down with a log line. A `gh issue|pr comment|create|edit` body, inline or
from `--body-file`/`-F`, is judged the same way a commit message already was.
Nothing to configure; the existing word list and patterns apply.
