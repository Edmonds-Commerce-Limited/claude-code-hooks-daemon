# Brainstorm — Secret File Read Blocker (Plan 00272)

Deep analysis supporting `PLAN.md`. This document is the durable record of the
threat model, honest limits, and design decisions' reasoning.

## Problem statement

Some files exist only to be consumed by tooling, never by an agent: Ansible
Vault password files, `.claude/block-words.secret`, private keys, API-token
files. An agent never needs their CONTENT — it needs to reason about their
PRESENCE (and perhaps metadata) to enable behaviour (e.g. pass
`--vault-password-file` to `ansible-vault`). Today nothing prevents the
content entering context: `Read` succeeds, `cat` succeeds, a `Grep` match can
echo a line. Once a secret is in context it is in the transcript, potentially
in logs, payload capture, memory files, and anything the agent later writes.

The existing `sensitive_content` handler is the OPPOSITE direction: it blocks
WRITING known terms, and only terms someone has already enumerated. This plan
blocks READING a file wholesale, without needing to know what is in it. The
two are complementary, not overlapping.

## Threat model — every route content can enter context

| Route                    | Mechanism                                                                                                                                                                                                                 | Coverage plan                                                                                                                                                                                                                                                                                                                   |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Read` tool              | direct                                                                                                                                                                                                                    | DENY when `file_path` matches a protected glob                                                                                                                                                                                                                                                                                  |
| `Bash` stdout            | `cat`, `head`, `tail`, `grep`, `sed -n`, `awk`, `cut`, `strings`, `base64`, `xxd`, `od`, `hexdump`, `dd`, `python -c 'open(...)'`, `openssl`, `rev`, `tac`, `paste`, `sort`, `uniq`, `wc -c` is safe-ish but see metadata | DENY any Bash command whose TEXT mentions a protected path (deny-by-default; see below)                                                                                                                                                                                                                                         |
| Copy-then-read           | `cp`/`mv`/`install`/`rsync`/`ln`/`tar`/`zip` the file to an unprotected path, then read the copy                                                                                                                          | same path-mention deny catches the copy step                                                                                                                                                                                                                                                                                    |
| Command substitution     | `echo "$(cat .vault-pass)"`, `VAR=$(< .vault-pass)`, `--vault-password-file <(cat f)`                                                                                                                                     | caught only when the protected path appears in the command text — which it must, to name the file. Substitution does not hide the path, so path-mention matching covers this                                                                                                                                                    |
| Indirection via variable | `F=.vault-pass; cat "$F"`                                                                                                                                                                                                 | the assignment line mentions the path → the whole invocation is denied. A path built by concatenation (`cat .vault-"pass"`, `cat .vault-p*`) is the honest-limits section                                                                                                                                                       |
| `Grep` tool              | content mode (`-c` output_mode "content") leaks matching lines                                                                                                                                                            | DENY Grep whose `path` matches, or whose search root could include the file with content output. Glob-scoped: deny when the resolved target matches a protected glob; for directory-rooted searches, rely on `-l`-style modes being names-only — content mode over a directory containing the file is the hard case; see limits |
| `Glob` tool              | names only                                                                                                                                                                                                                | ALLOW — presence is exactly what we want discoverable                                                                                                                                                                                                                                                                           |
| Environment              | `source .vault-pass.env`, `export $(cat f)`, `env`-dumping after sourcing                                                                                                                                                 | the sourcing command mentions the path → denied. An already-exported var is out of scope (it entered before the guard, or via a route outside tool calls)                                                                                                                                                                       |
| Agent subagents          | a subagent has its own tool calls — but the SAME daemon serves them (verified: subagents are blocked by PreToolUse hooks)                                                                                                 | covered automatically; note in docs                                                                                                                                                                                                                                                                                             |
| WebFetch/upload/Artifact | exfiltration of content ALREADY in context                                                                                                                                                                                | out of scope: the guard's job is to keep content out of context in the first place; `artifact_publish_blocker` covers artefact publishing                                                                                                                                                                                       |
| git                      | if the file is ever tracked, `git show`, `git diff`, `git log -p` leak it                                                                                                                                                 | protected files must be gitignored; ship an advisory/session-start check that each configured protected path IS ignored and NOT tracked. `git show :file` style commands also mention the path → denied                                                                                                                         |
| Read-adjacent metadata   | `wc -c`, `ls -l`, `stat`, `file`, `sha256sum`                                                                                                                                                                             | these reveal metadata, not content — but under deny-by-default they mention the path and are DENIED anyway, and the metadata helper is the sanctioned replacement. Simpler and safer than allowlisting each                                                                                                                     |

### Existence testing

`test -f`, `[ -e ... ]`, `ls` of the file name are legitimate ("presence
enables behaviour"). Options: (a) allowlist a narrow existence-test grammar,
or (b) route existence through the metadata helper too (`exists: true|false`).
(b) is simpler and keeps the deny rule absolute: **the ONLY Bash invocation
allowed to mention a protected path is the metadata helper, plus commands that
pass the path as an opaque argument to a trusted consumer** (see next).

### The trusted-consumer problem

The entire point of a vault password file is `ansible-vault --vault-password-file .vault-pass ...` /
`ansible-playbook --vault-password-file ...`. That command mentions the path
and must be ALLOWED — the consumer reads the file internally and never prints
it (modulo a hostile playbook, which is outside our trust boundary). So the
design needs an allowlist of consumer invocations where the path may appear as
an argument. Shape: a per-protected-path (or global) `allowed_consumers` list
of command-head patterns (`ansible-playbook`, `ansible-vault`, `ansible`),
with the rule that the path may only appear following a recognised
`--vault-password-file`-style flag — not in a substitution, not redirected.
Shipped defaults cover the Ansible family; projects extend via config.

## Honest limits — what a PreToolUse deny CANNOT guarantee

This is pattern matching on command text, not a sandbox. Enumerate honestly
(as `security_antipattern` guidance does):

1. **Constructed paths**: `cat .vault-"pass"`, `cat .vault-p?ss`, `cat $(echo LnZhdWx0LXBhc3M= | base64 -d)`, `find . -name '.vault-*' -exec cat {} \;`
   — the literal protected path never appears. Globs (`cat .vault-p*`) can be
   partially caught by also matching the glob against protected patterns, but
   full coverage is impossible.
2. **Scripts that open the file internally**: `python script.py` where the
   script hardcodes the path; `make deploy`; any binary. The command text is
   clean. Unfixable at this layer.
3. **Directory-rooted content search**: `grep -r password .` over a tree
   containing the file; the Grep tool in content mode rooted above the file.
   Mitigation: the daemon could expand protected globs and deny recursive
   content-grep whose root is an ancestor — expensive and still leaky (`awk`,
   `python`). Decide: best-effort for the common `grep -r` shapes only.
4. **Non-tool routes**: the user pastes the content; an MCP tool reads it; a
   hook or supervisor script leaks it into injected context. Outside the
   daemon's visibility.
5. **Pre-existing exposure**: content already in context, in a transcript, in
   an env var exported before the guard, or committed to git history.

Framing follows `sed_blocker`: **DENY-BY-DEFAULT, not a list of bad
patterns**. The rule is "any Bash command whose text mentions a protected
path is denied", with two narrow exemptions (metadata helper; allowlisted
consumer with the path in flag position). Everything the limits list above
describes is a documented residual risk, stated in `get_claude_md()` guidance
so agents do not read an unblocked command as permission — same doctrine as
the markdown_organization bash-coverage note.

Defence in depth: the guard makes accidental/casual reads impossible and
deliberate circumvention require constructions that are themselves visible in
the transcript as obvious evasion. That is the realistic security claim.

## The metadata helper

`bin/hooks-daemon secret-meta <path>` (name TBD) returns, as JSON:

- `path`, `exists`, `size_bytes`, `mtime`, `mode` (permissions), `owner`
- optionally a content digest (see below)
- never content; implemented to read the file only for the digest, and to
  hold content in memory only transiently (best-effort in Python).

The helper's invocation is the one universally-exempt way to mention a
protected path in Bash. It also answers existence testing.

### Does hashing leak?

Yes, for low-entropy secrets: sha256 of a weak passphrase is offline
brute-forceable — publishing the hash in a transcript is equivalent to
publishing a crackable commitment. Options:

1. Plain sha256 — useful (compare two deployments, detect change), but leaks
   as above.
2. Salted/keyed digest: HMAC-SHA256 with a per-project random key stored in a
   gitignored, ITSELF-PROTECTED file (e.g.
   `.claude/hooks-daemon/untracked/secret-meta.key`, generated on first use).
   Preserves "did it change?" and "are these two files identical?" (same key)
   while being useless offline without the key.
3. Make any digest opt-in.

**Recommendation**: default to keyed HMAC (option 2); expose plain sha256
only behind an explicit config flag (`allow_plain_hash: true`) for projects
that need cross-machine comparison and accept the leak. `size_bytes` also
leaks a little (password length) — acceptable, but note it; consider a
`min_size_bucket` rounding option only if a reviewer wants it (YAGNI lean:
report exact size, document the leak).

## Config shape

```yaml
handlers:
  pre_tool_use:
    secret_file_guard:
      enabled: true
      options:
        protected_paths:            # gitignore-style globs, additive to defaults
          - "secrets/prod-token"
        include_default_paths: true # ship-on defaults below
        allowed_consumers:          # additive to shipped Ansible defaults
          - command: "my-deploy-tool"
            path_flags: ["--secret-file"]
        allow_plain_hash: false
```

Shipped default globs (default-on, additive): `.vault-pass*`,
`*.vault-password`, `*vault_pass*`, `.claude/block-words.secret`, `*.pem`
(discuss — likely too broad; keys often need reading for debugging? No:
private keys are exactly the class that never needs reading. But `*.pem` also
matches PUBLIC certs. Narrow to `*.key`? Open question for human), plus
`id_rsa`/`id_ed25519`-style names? **Recommendation**: ship a SHORT
conservative default list (vault-password shapes + the daemon's own secret
word list) default-ON, and document how to add key material patterns.
Rationale for default-on: a guard that ships empty protects nobody (the
`sensitive_content` secret list is "silently inert" when empty — this plan
should not repeat that for its defaults); a false positive here costs one
config edit, a false negative costs a leaked credential.

Note `worktree_create` seeds `.claude/block-words.secret` by symlink into
worktrees — protection must apply to the symlink path AND its target
(resolve realpath before matching, and match on both spellings).

## No escape hatch — same reasoning as artifact_publish_blocker

No `MUST_READ_SECRET_BECAUSE`. An agent that can type its own justification
has self-authorised disclosure — exactly what the guard exists to prevent
(Plan 00259 doctrine). A HUMAN lifts protection by editing
`protected_paths` / disabling the handler in config. `get_claude_md()`
guidance says so explicitly and tells agents not to hunt for another way.

## Reverse direction, deletion, scope decisions

- **Copy/move elsewhere**: covered by the path-mention deny (the `cp` names
  the path). No separate mechanism needed. Writing INTO a protected file
  (`Write`/`Edit`/`>`): deny too — an agent has no business rewriting a
  vault password, and allowing writes invites a read-modify-write dance.
  Cheap to include since the same matching applies.
- **Deletion** (`rm .vault-pass`): destroys availability, not
  confidentiality. The path-mention deny catches it anyway as a side effect —
  which is fine and arguably good. Decision: no dedicated deletion logic
  (YAGNI); it falls out of deny-by-default, document that.
- **Read of a protected path by ANOTHER tool** (NotebookEdit, MCP tools): out
  of scope for v1; note as residual risk. The daemon only sees wired events.

## Interaction with existing handlers

- `sensitive_content`: complementary (write-direction, term-based). The
  secret word list FILE becomes a shipped protected path here — closing the
  loop: today an agent may open it "to see what matched"; after this plan it
  cannot, and the deny reason should instead say "ask the user". This CHANGES
  documented `sensitive_content` guidance ("open the secret word list file if
  you have access") — a truth-change manifest entry is required at release.
- Plan 00252 (staged-content secret scan): commit-time, term-based; no
  overlap, cite as sibling.
- `root_recursion_guard`, `pipe_blocker`: unrelated mechanics; priority
  ordering must put this guard in the safety band so it answers before
  advisory handlers.
- Verdict log: the deny reason must NAME the matched glob but never quote
  file content (there is none to quote — the guard fires pre-read).

## Handler shape

- Event: PreToolUse, `PreToolUseHandlerBase`, `GatingResult`,
  `Decision.DENY`, `terminal=True`.
- Priority: safety band 10–20; suggest **14** alongside
  `sensitive_content`/`security_antipattern` (or 13/15 if 14 is judged
  crowded — final slot at implementation time from the live table).
- Tools matched: `Read`, `Write`, `Edit`, `Bash`, `Grep` (and `NotebookEdit`?
  — decide at implementation; cheap to include for `notebook_path`).
- Glob matching: reuse the daemon's existing gitignore-style glob utilities
  (`exclude_paths` machinery) — DRY.
- Metadata helper: CLI subcommand in `daemon/cli.py` (+ core logic in
  `utils/` for unit-testability), NOT a loose script, so it rides the
  deployed wrapper and needs no PATH management.

## Acceptance-test note

Testing a read-guard must never actually read a real secret. Fixture: a
generated dummy file in a temp dir configured as protected for the test
session, or `echo`-embedded protected path names (the guard matches on path
mention, so `echo ".vault-pass"` — decide whether echo is exempt like
sed_blocker's exemption 4, or denied; **recommendation: NO echo exemption** —
unlike sed, there is no legitimate need to echo a protected path, and every
exemption is attack surface. Commit messages mentioning a protected path:
follow sed_blocker's narrow `git commit -m` exemption? Probably yes, or
committing this plan's own docs becomes awkward — but note the path names are
not secrets, only contents are. **Recommendation: match only on the path as a
shell WORD/argument, so prose mentions in `-m` strings are naturally rare;
add the git-commit-message exemption only if dogfooding shows it needed.**)
