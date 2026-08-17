# Documentation Conventions

Conventions for tracked markdown in this repository. Each one exists because a
reader acted on a document and it did not work.

## Claude Code skill invocations: ```` ```claude-code ````

A Claude Code slash command is typed **into the Claude Code chat**. It is not
shell. Pasted into a terminal it fails:

```
bash: /hooks-daemon: No such file or directory
```

**The canonical form is a ```` ```claude-code ```` fence, and nothing else:**

````markdown
```claude-code
/hooks-daemon upgrade
```
````

**Never put a slash command in a ```` ```bash ````, ```` ```sh ````, ```` ```shell ````,
```` ```console ```` or ```` ```zsh ```` fence.** Those tags assert "this block is runnable
shell", which is precisely the false claim. This is not a style preference: a
reader who trusts the tag gets an error, and the tag is the only thing that told
them to.

**Never mix shell and slash commands in one fence.** A fence carries exactly one
language. When a task can be done both ways, show them as two blocks and say
which is which:

````markdown
**In the Claude Code chat:**

```claude-code
/hooks-daemon upgrade
```

**From a terminal:**

```bash
.claude/skills/hooks-daemon/scripts/upgrade.sh
```
````

`claude-code` is not a highlighter language, which is the point — renderers show
the block as plain text rather than colouring it as shell. `mdformat` (run over
every markdown write by the `markdown_table_formatter` handler) preserves the
info string unchanged.

### Why a fence tag rather than prose

Prose ceremony ("this is a chat command, not shell") is easy to omit and
impossible to check. The tag travels with the block, survives copy-paste into
another document, and is mechanically enforceable — which is what stops the
convention decaying.

## Daemon CLI invocations must name a real subcommand

A `bin/hooks-daemon <subcommand>` invocation inside a shell-tagged fence is
checked against the **live** argparse registry by
`scripts/qa/check_doc_truth.py`. The registry is read by asking the CLI to
render itself, never by restating it in the checker.

`RELEASES/v3.53.0.md` shipped `.claude/hooks-daemon/bin/hooks-daemon upgrade`,
which exits 2 — there is no `upgrade` subcommand. Upgrading is reachable, but
through the **skill** (`/hooks-daemon upgrade`), so the words were right and
only the form was wrong. That is exactly the shape review misses.

## Enforcement

Both rules are enforced by `scripts/qa/check_doc_truth.py`, which runs in the QA
suite:

```bash
./scripts/qa/llm_qa.py doc_truth
```

Rules:

| Rule                           | Meaning                                                           |
| ------------------------------ | ----------------------------------------------------------------- |
| `cli-subcommand-unknown`       | `bin/hooks-daemon <sub>` names a subcommand the CLI does not have |
| `slash-command-in-shell-fence` | A Claude Code slash command sits in a shell-tagged fence          |

### How the checker avoids guessing

Three discriminators, each of which caught a false positive that a simpler rule
would have reported:

**The fence's language tag, not the fence.** `CLAUDE/AgentTeam.md` keeps English
prose inside *untagged* fences, and one line reads "Run the daemon CLI as
`./bin/hooks-daemon` from inside that worktree". A fence-only rule reads `from`
as a subcommand, at seven sites.

**A slash command must resolve to a real skill.** Skill directory names under
`.claude/skills/` and `src/claude_code_hooks_daemon/skills/` are the allowlist.
`CLAUDE/Worktree.md` shows `git worktree list` OUTPUT inside a shell fence,
whose rows begin `/workspace  abc1234 [main]` — a leading slash in a shell block
is often a path, and only "does this name a skill?" separates the two.

**Vendored content is never scanned.** `.claude/ccy/plugins/.../marketplaces/`
holds a third-party plugin catalogue this project does not author; 11 of its
READMEs matched before that exclusion existed.

### What the fence-tag rule does NOT cover

`RELEASES/` and `CLAUDE/Plan/` are exempt from `slash-command-in-shell-fence`,
though not from `cli-subcommand-unknown`. The asymmetry is deliberate. A
nonexistent subcommand is simply **wrong** and stays wrong, so it is worth
correcting wherever it appears — there was exactly one. A slash command in a
shell fence is **mis-tagged**: the command is right and works when typed into
the chat, so the cost is a reader's misstep rather than a broken instruction.
Rewriting 47 published release notes and the closed-plan record to change a tag
would edit history for the lesser fault. New material gets the convention; the
archive keeps what it said at the time.
