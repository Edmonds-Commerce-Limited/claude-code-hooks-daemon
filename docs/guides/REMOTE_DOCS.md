# Vendoring remote documentation

Capture documentation from the web into your repository, so your team and your
agents can read and grep it offline instead of re-fetching it.

Full detail — the provenance schema, the fidelity rule and what enforces
it — lives in [CLAUDE/RemoteDocs.md](../../CLAUDE/RemoteDocs.md). Per-handler
options are in [HANDLER_REFERENCE.md](HANDLER_REFERENCE.md).

## Capture a page

```bash
bin/hooks-daemon remote-docs add https://docs.example.com/guide
```

That writes `remote-docs/docs.example.com/guide.md`, with frontmatter
recording where it came from, when, a content hash, its licence and how long
it stays fresh. You never write these files by hand — that is blocked.

## The everyday commands

| Command                             | What it does                                   |
| ----------------------------------- | ---------------------------------------------- |
| `remote-docs add <url>`             | Capture a page                                 |
| `remote-docs add <url> --verbatim`  | Store the raw response body, not an extraction |
| `remote-docs list`                  | What is vendored                               |
| `remote-docs check`                 | What is stale or unreadable (exit 1 if any)    |
| `remote-docs refresh --path <file>` | Re-fetch one document                          |
| `remote-docs refresh --all`         | Re-fetch everything                            |

A refresh that finds upstream unchanged says `unchanged` and rewrites nothing
but the dates.

`.claude/REMOTE-DOCS.md` is regenerated on every capture and refresh — one
grep there answers "do we already have docs for X?".

## Configure it

```yaml
documentation:
  trees:
    remote: remote-docs
  remote:
    default_staleness_days: 90
    known_sources:
      docs.python.org: PSF-2.0
      docs.example.com: unreviewed
```

`known_sources` earns its keep twice. It fills in the licence automatically, so
that review happens once per site rather than once per file. And it tells the
daemon which sites are documentation sources: fetching an uncaptured page from
one of them prompts you to vendor it, while every other site stays silent.

List a site with `unreviewed` to declare it before you have checked its
licence.

## What you will notice

- **Fetching a page you already have** is blocked, and the message names the
  local file. If you genuinely need newer content, refresh it.
- **Reading a stale document** tells you so at that moment, with the refresh
  command.
- **Session start** reports anything stale, and is silent when nothing is.

Staleness only ever advises — an upstream that has not changed is not a
problem. Missing provenance blocks, because a document with no recorded source
cannot be refreshed or trusted.

## Getting better captures

Install [`agent-browser`](https://github.com/anthropics/agent-browser) and put
it on `PATH`. Captures then negotiate markdown and follow `llms.txt`, which
produces markedly better documentation than a plain fetch. Without it,
everything still works and the daemon tells you what you are missing.
