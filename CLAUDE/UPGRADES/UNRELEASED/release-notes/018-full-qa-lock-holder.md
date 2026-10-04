# Fix: the full-QA lock file names the process that holds the lock

**Plan**: 00474
**Audience**: contributors who run QA

`.git/hooksdaemon-full-qa.lock` could name a holder that had exited hours earlier: `llm_qa.py` wrote its pid and checkout and left them there after releasing, while `run_tests.sh` held the lock and wrote nothing. Both routes now write their own `pid=`, `checkout=` and `started=` lines once they hold the lock, and always overwrite the whole file when they acquire it. `llm_qa.py` also empties the file when it releases. `run_tests.sh` does not clear on exit (the kernel drops the lock when the process exits), so a line left by a finished shell names a dead pid, which readers already treat as no holder. The file is never deleted: a lock on an unlinked file excludes nobody.
