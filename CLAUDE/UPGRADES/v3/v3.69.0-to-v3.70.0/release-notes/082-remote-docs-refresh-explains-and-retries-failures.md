# Callout: `remote-docs refresh` says why a document failed, retries once, and stops closing every browser

**Plan**: 00474
**Audience**: client projects

`hooks-daemon remote-docs refresh` printed `<path>: failed` with no reason, and nothing retried. On a large refresh about half the documents failed that way and each succeeded when refreshed alone.

- **The cause is printed.** A failed document now has an indented line under it naming the cause (the fetcher's own error text, or the file it could not write).
- **A failed fetch is retried once**, after a two second pause. A document that recovers reports its normal outcome.
- **The race is fixed at its source.** Each browser read now runs in its own named agent-browser session and closes only that session. It used to run `agent-browser close --all` after every read; that returns before the shared browser daemon has exited, so the next read reached the dying daemon and got an empty response (7 of 15 back-to-back reads failed that way, none did with one session per read). `close --all` also ended every other agent's browser on the machine. Nothing needs to change in your config.
