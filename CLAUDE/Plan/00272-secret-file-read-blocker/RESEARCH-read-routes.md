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

Every row must end Phase 1 with visibility + classification + notes filled.

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

### Bash — direct readers (command text names the path)

`cat, head, tail, less, more, sed -n, awk, cut, tr, sort, uniq, rev, tac, base64, xxd, od, hexdump, strings, dd, split, fold, nl, paste, tee, grep, wc, file`, redirection `< file`, `$(<file)`, `$(cat file)`, command
substitution nested in any otherwise-allowed command, unquoted-heredoc
interpolation.

| Aspect                                                                                                                                       | Visibility      | Class | Notes                                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Any of the above with the literal path in command text                                                                                       | PreToolUse Bash | (b/c) | deny-by-default on path mention catches ALL of them uniformly — the reader list never needs to be complete. Class (b) for literal mentions, (c) overall because of constructed paths below |
| Interpreter one-liners naming the path (`python -c "open('.vault-pass').read()"`, `perl -e`, `ruby -e`, `node -e fs.readFileSync`, `php -r`) | PreToolUse Bash | (b/c) | same path-mention rule; the interpreter is irrelevant                                                                                                                                      |

### Bash — path-obfuscation evasions

| Route                                                                           | Visibility | Class                  | Notes                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------- | ---------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Relative vs absolute spelling, `./`, `..` traversal                             | PreToolUse | (b) with normalisation | matcher must canonicalise both config globs and command tokens                                                                                                                                             |
| `~`, `$HOME`, `$PWD` prefixes                                                   | PreToolUse | (c)                    | expand the known prefixes before matching (markdown_organization precedent: separate raw `$HOME` scan)                                                                                                     |
| Variable indirection in ONE invocation (`P=.vault-pass; cat "$P"`)              | PreToolUse | (b)                    | the assignment token mentions the path → whole invocation denied                                                                                                                                           |
| Variable set in an EARLIER invocation, used later (`cat "$P"`)                  | PreToolUse | (d)/(c)                | later command text is clean. DECIDE: deny any Bash command combining a bare variable expansion with a read-capable head + a protected BASENAME appearing anywhere? Research must weigh false-positive cost |
| Glob/wildcard construction (`cat .vault-p*`, `?`)                               | PreToolUse | (c)                    | match command glob tokens AGAINST protected patterns (bidirectional matching) — partial coverage                                                                                                           |
| String assembly (`cat .vault-"pass"`, `$(echo …base64…)`, `printf`-built paths) | PreToolUse | (d)                    | undecidable; residual risk                                                                                                                                                                                 |
| `find -name '.vault-*' -exec cat {} \;`, `xargs cat`                            | PreToolUse | (c)                    | pattern appears; deny find/-exec/xargs combos whose name-pattern intersects protected globs — heuristic                                                                                                    |
| Symlink/hardlink aliasing (`ln -s .vault-pass x; cat x`)                        | PreToolUse | (c)                    | the LINK-CREATING command mentions the path → denied; a PRE-EXISTING alias is (d). realpath-resolve protected paths at config load; consider inode-level impossible at text level                          |

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

- **Verify**: does the daemon receive full Bash stdout/stderr in the
  PostToolUse payload? (`scripts/debug_hooks.sh` capture; cross-check
  `CLAUDE/Code/HooksSystem.md`.) TBC
- Detection options: match output substrings against the file's actual
  first/last N bytes or rolling hashes — **requires the DAEMON itself to
  read the secret** (in-process, never emitted, never logged). DECIDE:
  is daemon-side reading acceptable, or also forbidden? Note PostToolUse
  fires AFTER the content is already in context — a deny is a failure
  report + "do not repeat", not prevention. Value: catches routes (c)/(d)
  missed upstream; cost: secret in daemon memory + inherent lateness.

### Other surfaces

| Route                                           | Visibility | Class   | Notes                                                                                              |
| ----------------------------------------------- | ---------- | ------- | -------------------------------------------------------------------------------------------------- |
| Subagents (Agent tool)                          | same hooks | TBC→(b) | believed covered (same daemon serves them); VERIFY live, do not assume                             |
| MCP tools reading files                         | TBC        | TBC     | are MCP tool calls wired through PreToolUse in this daemon? Verify; likely (d) if unwired          |
| WebFetch `file://`                              | TBC        | TBC     | verify whether WebFetch accepts file URLs at all                                                   |
| Artifact `upload_asset` of a protected file     | PreToolUse | (b)     | artifact_publish_blocker already denies publish; confirm upload_asset is covered or add path match |
| User pastes content; supervisor/hook injects it | none       | (d)     | outside daemon visibility                                                                          |

## Phase 1 verification checklist (no assumptions)

1. `debug_hooks.sh` capture: PostToolUse payload for a Bash command — does
   `tool_response` carry full stdout/stderr?
2. Live subagent probe: confirm a spawned agent's Read/Bash calls hit the
   same PreToolUse chain.
3. Grep tool payload shapes: which fields expose output mode, path, root.
4. Edit-on-protected-file error/echo behaviour.
5. WebFetch `file://` and MCP tool event wiring.
6. Bidirectional glob matching feasibility on command tokens.

## Conclusion to be written after research

Summary classification table (counts of b/c/d), the recommended layer stack,
and the plainly-stated residual risk that only OS-level controls close.
