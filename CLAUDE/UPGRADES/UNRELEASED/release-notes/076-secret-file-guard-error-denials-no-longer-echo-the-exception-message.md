# Callout: `secret_file_guard` error denials no longer echo the exception message

**Plan**: 00466
**Audience**: client projects

An evaluation-error deny named both the exception TYPE and its full message
text. No raise path today carries a discovered filename into that message,
but the project's own rule for a directory-rooted search is that a name
DISCOVERED by the walk must never be echoed back — and a future `OSError`
from a stat call could easily carry one. The deny reason now names only the
exception type; the full message still reaches the daemon's own log.
