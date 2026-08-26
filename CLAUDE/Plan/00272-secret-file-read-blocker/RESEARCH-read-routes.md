# RESEARCH — Read Routes (Plan 00272)

**Status of this document**: SCAFFOLD. Phase 1 of the plan fills in every
`TBC` cell with VERIFIED findings (via `scripts/debug_hooks.sh` captures and
live probes), not assumptions. Nothing here is a design commitment until the
classification is complete.

## Purpose

Exhaustively enumerate every route by which the content of a protected file
can reach agent context, and classify each. The honest conclusion this
research must reach: hook-level protection is DEFENCE IN DEPTH, not a
sandbox; only OS-level controls (file permissions, a separate user, agent
sandboxing) can truly guarantee non-disclosure. The design then takes the
strongest feasible layers.

## Classification legend

- **(a) Visibility**: which hook event/tool call lets the daemon see the
  attempt at all (PreToolUse Read/Bash/Grep/Edit, PostToolUse tool_response,
  none).
- **(b) RELIABLE**: deniable with essentially no false negatives.
- **(c) HEURISTIC**: deniable only by pattern heuristics; evasions exist.
- **(d) UNBLOCKABLE**: fundamentally invisible or undecidable at hook level.

## Route inventory

Every row must end Phase 1 with visibility + classification + notes filled,
PLUS an **expected verdict** (DENY / ALLOW / ADVISE / out-of-scope) per route —
that column is what Task 7.1's acceptance tests assert against, so "shipped
class-(c) heuristics behave as specified" has a concrete referent.

### Dedicated tools

| Route                                                     | Visibility | Class | Notes                                                                                            |
| --------------------------------------------------------- | ---------- | ----- | ------------------------------------------------------------------------------------------------ |
| `Read` tool on protected path                             | PreToolUse | (b)   | exact `file_path` match after normalisation (absolute enforced by `absolute_path`)               |
| `Grep` tool, path = protected file                        | PreToolUse | (b)   | deny content output modes                                                                        |
| `Grep` tool, content mode rooted at an ancestor directory | PreToolUse | TBC   | matching lines leak; decide deny-vs-best-effort; verify what payload fields expose mode and root |
| `Glob` tool                                               | PreToolUse | safe  | names only — deliberately ALLOWED (presence is the feature)                                      |
| `Edit` old_string echo-back                               | TBC        | TBC   | can an Edit on a protected file leak content via error messages / diffs? Verify                  |
| `Write` clobber interaction                               | PreToolUse | (b)   | writes denied outright (no legitimate use); confirm no read-back path                            |
| `NotebookEdit`                                            | TBC        | TBC   | notebook_path route; verify event shape                                                          |
| `LSP` tools (hover, documentSymbol) on a protected file   | TBC        | TBC   | LSP responses can return file text; verify whether LSP calls are wired through PreToolUse        |
| `TaskOutput` relaying a subagent's output                 | TBC        | TBC   | Task 1.2's subagent PreToolUse check does NOT cover this relay surface — verify separately       |
| `Skill` invocation whose body reads files                 | TBC        | TBC   | a skill body can read files; verify what events its internal reads fire                          |

### Bash — direct readers (command text names the path)

`cat, head, tail, less, more, sed -n, awk, cut, tr, sort, uniq, rev, tac, base64, xxd, od, hexdump, strings, dd, split, fold, nl, paste, tee, grep, wc, file`, redirection `< file`, `$(<file)`, `$(cat file)`, command
substitution nested in any otherwise-allowed command, unquoted-heredoc
interpolation.

| Aspect                                                                                                                                       | Visibility      | Class | Notes                                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Any of the above with the literal path in command text                                                                                       | PreToolUse Bash | (b/c) | deny-by-default on path mention catches ALL of them uniformly — the reader list never needs to be complete. Class (b) for literal mentions, (c) overall because of constructed paths below |
| Interpreter one-liners naming the path (`python -c "open('.vault-pass').read()"`, `perl -e`, `ruby -e`, `node -e fs.readFileSync`, `php -r`) | PreToolUse Bash | (b/c) | same path-mention rule; the interpreter is irrelevant                                                                                                                                      |

### Bash — path-obfuscation evasions

| Route                                                                                                                                                         | Visibility | Class                  | Notes                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Relative vs absolute spelling, `./`, `..` traversal                                                                                                           | PreToolUse | (b) with normalisation | matcher must canonicalise both config globs and command tokens                                                                                                                                                                                                                                                                                                              |
| `~`, `$HOME`, `$PWD` prefixes                                                                                                                                 | PreToolUse | (c)                    | expand the known prefixes before matching (markdown_organization precedent: separate raw `$HOME` scan)                                                                                                                                                                                                                                                                      |
| Variable indirection in ONE invocation (`P=.vault-pass; cat "$P"`)                                                                                            | PreToolUse | (b)                    | the assignment token mentions the path → whole invocation denied                                                                                                                                                                                                                                                                                                            |
| Persistent shell state across invocations (variable set earlier then `cat "$P"`; `exec 3<file` then read fd; `mkfifo` + background writer; tmux/screen panes) | PreToolUse | (d)/(c)                | later command text is clean — one row generalising every cross-invocation-state trick. DECIDE: deny any Bash command combining a bare variable expansion with a read-capable head + a protected BASENAME appearing anywhere? Research must weigh false-positive cost; the fd/fifo/tmux variants are (c) only at the SETUP step (which mentions the path) and (d) afterwards |
| Process substitution (`--vault-password-file <(cat f)`, `diff <(cat f) x`)                                                                                    | PreToolUse | (b/c)                  | the inner command names the path, so path-mention matching sees it — but the consumer-allowlist grammar must NOT treat `<(...)` as flag-position (it hands content to the outer command)                                                                                                                                                                                    |
| Glob/wildcard construction (`cat .vault-p*`, `?`)                                                                                                             | PreToolUse | (c)                    | match command glob tokens AGAINST protected patterns (bidirectional matching) — partial coverage                                                                                                                                                                                                                                                                            |
| String assembly (`cat .vault-"pass"`, `$(echo …base64…)`, `printf`-built paths)                                                                               | PreToolUse | (d)                    | undecidable; residual risk                                                                                                                                                                                                                                                                                                                                                  |
| `find -name '.vault-*' -exec cat {} \;`, `xargs cat`                                                                                                          | PreToolUse | (c)                    | pattern appears; deny find/-exec/xargs combos whose name-pattern intersects protected globs — heuristic                                                                                                                                                                                                                                                                     |
| Symlink/hardlink aliasing (`ln -s .vault-pass x; cat x`)                                                                                                      | PreToolUse | (c)                    | the LINK-CREATING command mentions the path → denied; a PRE-EXISTING alias is (d). realpath-resolve protected paths at config load; consider inode-level impossible at text level                                                                                                                                                                                           |

### Bash — relocation then read

`cp/mv/install/dd/ln/tar/zip/rsync` to an unprotected path, then read the
copy. The relocation command mentions the path → denied (b/c). A copy made
BEFORE protection existed, or by an external process, is (d).

### Scripts and programs that open the file internally

| Route                                                         | Visibility                   | Class | Notes                                                                                                                                                       |
| ------------------------------------------------------------- | ---------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent WRITES a script referencing the path, then executes it  | PreToolUse Write/Edit + Bash | (c)   | secondary layer: content-scan Write/Edit for protected paths (sensitive_content-style) so the script cannot be authored; the execution line itself is clean |
| Pre-existing script/binary/Makefile that reads it             | none                         | (d)   | command text clean, content unseen. UNBLOCKABLE — headline residual risk                                                                                    |
| Bash-authored script via heredoc/redirect (content guard gap) | PostToolUse?                 | TBC   | verify whether lint_on_edit-style bash-write detection can carry a protected-path content scan                                                              |

### git and environment

| Route                                                                     | Visibility      | Class   | Notes                                                                                                                                                         |
| ------------------------------------------------------------------------- | --------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| File tracked in git: `git show/diff/log -p/stash show -p`                 | PreToolUse      | (c)     | commands mention the path or leak via revision syntax (`git show :./.vault-pass`); primary mitigation = MUST be gitignored + session-start tracked-file check |
| Sourcing the file (`source f`, `. f`, `export $(cat f)`)                  | PreToolUse      | (b)     | path mention                                                                                                                                                  |
| Already-exported env var (`env`, `printenv`)                              | none/PreToolUse | (d)     | content entered before guard; out of scope                                                                                                                    |
| Consumer reads (`ansible-vault/ansible-playbook --vault-password-file f`) | PreToolUse      | ALLOWED | the CONSUMER may read it; the AGENT's context must not. Allowlist grammar: path only in flag position                                                         |

### Output-side (secondary layer) — TBC, key verification target

The leak VECTOR is tool output: a route only matters if content reaches
stdout/stderr or a readable artifact. Candidate backstop: a PostToolUse scan
of Bash `tool_response` for protected-file content.

**The vendored contract answers the shape questions for free.**
`contracts/claude-code-hooks/PostToolUse.json` lists `updatedToolOutput` and
`updatedMCPToolOutput` among the hook-specific output fields — so PostToolUse
can in principle REWRITE the tool result before it reaches context. If Claude
Code honours that field for Bash, the backstop is genuine REDACTION, not a
post-hoc failure report, and the earlier framing "PostToolUse fires after the
content is already in context — a deny is only a report" is WRONG for the
rewrite path (it remains true for a plain deny). This also shrinks class (d):
a pre-existing script that prints the secret is invisible at PreToolUse, but
its OUTPUT is visible — and rewritable — at PostToolUse. Re-derive the
class-(d) list after this is verified.

- **Verify (contracts first, live capture only for behaviour)**: the contract
  gives payload shape; `scripts/debug_hooks.sh` + a live probe answer the
  behaviour questions — does `tool_response` carry full stdout/stderr, and
  does Claude Code actually honour `updatedToolOutput` for Bash (substituted
  output reaches context, original does not)? TBC
- Detection options: match output substrings against the file's actual
  first/last N bytes or rolling hashes — **requires the DAEMON itself to
  read the secret** (in-process, never emitted, never logged). DECIDE: is
  daemon-side reading acceptable, or also forbidden? If `updatedToolOutput`
  works, the cost/benefit changes entirely: secret-in-daemon-memory buys
  PREVENTION (redacted substitution), not merely a report. Any such
  in-memory digests must be architecturally separate from the `secret-meta`
  helper's public digest (see BRAINSTORM.md — extraction-oracle risk).
- The decision must be written as an AMENDMENT to
  `utils/secret_redaction.py`'s doctrine ("exactly one code path ever reads
  the raw terms"), not alongside it — see the daemon-owned-outputs section
  below.

### Daemon-owned outputs — a route class in its own right

The tables above enumerate routes into AGENT context; the daemon's own
artefacts are a second destination and must be classified too.
`utils/secret_redaction.py` already enumerates the daemon-owned leak vectors
(payload capture, router debug log, front-controller error log, transcript
archives) and records the Plan 00233 known gap. Critically,
`daemon/payload_capture.py` redacts **only terms from the configured secret
word list** — so for any route classified (c)/(d) here that SUCCEEDS, the
PostToolUse payload carrying the secret is written verbatim to
`payload-capture/`. Shipping this guard without closing that would WORSEN the
on-disk artefact footprint for exactly the routes the guard misses.

| Route                                                                                                              | Visibility  | Class | Notes                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------ | ----------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Payload capture of a successful read's PostToolUse payload                                                         | daemon-side | TBC   | extend `redact_structure` (or exclude protected-path payloads from capture) BEFORE any output-side layer is built                        |
| Router debug log / front-controller error log echoing payload fragments                                            | daemon-side | TBC   | same redaction seam; verify coverage                                                                                                     |
| Daemon linter handlers quoting content: `staged_lint_gate` ("first line of diagnosis"), `lint_on_edit` diagnostics | daemon-side | TBC   | if a protected file is ever staged or edited, a linter diagnostic can quote a content line into context — protected paths need excluding |

### Auto-inlining with no tool call at all

A protected path reached by an `@`-import in `CLAUDE.md`, or matched by a
`paths:` glob in `.claude/rules/*.md`, is inlined by Claude Code with **no
hook event**. Class (d) by tool visibility — but unlike most (d) routes it is
a *configuration* condition the daemon CAN check at session start (does any
`@`-import or rules glob cover a protected path?). Worth a session-start
advisory row rather than a shrug.

### Other surfaces

| Route                                           | Visibility | Class   | Notes                                                                                              |
| ----------------------------------------------- | ---------- | ------- | -------------------------------------------------------------------------------------------------- |
| Subagents (Agent tool)                          | same hooks | TBC→(b) | believed covered (same daemon serves them); VERIFY live, do not assume                             |
| MCP tools reading files                         | TBC        | TBC     | are MCP tool calls wired through PreToolUse in this daemon? Verify; likely (d) if unwired          |
| WebFetch `file://`                              | TBC        | TBC     | verify whether WebFetch accepts file URLs at all                                                   |
| Artifact `upload_asset` of a protected file     | PreToolUse | (b)     | artifact_publish_blocker already denies publish; confirm upload_asset is covered or add path match |
| User pastes content; supervisor/hook injects it | none       | (d)     | outside daemon visibility                                                                          |

## Phase 1 verification checklist (no assumptions)

1. Contracts first: read `contracts/claude-code-hooks/PostToolUse.json` (and
   siblings) for payload/output shape — including `updatedToolOutput`. Then
   `debug_hooks.sh` + live probe for BEHAVIOUR only: does `tool_response`
   carry full stdout/stderr, and does Claude Code honour `updatedToolOutput`
   for Bash?
2. Live subagent probe: confirm a spawned agent's Read/Bash calls hit the
   same PreToolUse chain — AND separately verify the `TaskOutput` relay
   surface, which the subagent probe does not cover.
3. Grep tool payload shapes: which fields expose output mode, path, root
   (contract files first, capture second).
4. Edit-on-protected-file error/echo behaviour.
5. WebFetch `file://`, MCP tool event wiring, LSP and Skill surfaces.
6. Bidirectional glob matching feasibility on command tokens.
7. Daemon-owned outputs: confirm what payload capture / debug logs record for
   a successful protected-file read, and what `staged_lint_gate` /
   `lint_on_edit` would quote for a staged/edited protected file.
8. Auto-inlining config check feasibility: `@`-imports and `.claude/rules/`
   `paths:` globs vs protected globs at session start.

## Conclusion to be written after research

Summary classification table (counts of b/c/d), the recommended layer stack,
and the plainly-stated residual risk that only OS-level controls close.
