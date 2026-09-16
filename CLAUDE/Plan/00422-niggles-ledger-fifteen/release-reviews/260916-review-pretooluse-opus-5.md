# Release code review: pre_tool_use + post_tool_use handlers (v3.64.0..HEAD)

Scope: `git diff v3.64.0..HEAD -- src/claude_code_hooks_daemon/handlers/pre_tool_use/
src/claude_code_hooks_daemon/handlers/post_tool_use/` — 20 files, +989/-301.
Reviewed against RELEASING.md Step 10. Every finding was reproduced against the
shipped code.

Suites run during the review (all green): test_worktree_file_copy,
test_guard_config_commit_gate, test_sensitive_content, test_destructive_git_prose,
test_tdd_enforcement, test_ask_user_question_blocker, test_project_containment,
test_remote_docs_provenance, test_validate_eslint_on_write — 732 passed, 1 xfailed.
Every defect below is a hole the suite does not cover.

---

## DEFECTS (must fix before the release ships)

### D1 — `gh issue create --title "<term>"` is no longer scanned (regression vs v3.64.0)

`handlers/pre_tool_use/sensitive_content.py:260-275` (`_GH_BODY_PATTERN`, `_GH_BODY_FLAGS`)

The surface inventory was widened (good: release/gist/repo now covered) but the
match was simultaneously narrowed by a lookahead requiring a BODY flag. `--title`
is not in `_GH_BODY_FLAGS`, and a title is published prose on the same
irretractable public page a body is.

Reproduced against the shipped handler:

    SensitiveContentHandler()._bash_haystacks(
        {"tool_name": "Bash",
         "tool_input": {"command": 'gh issue create --title "secret-host-name"'}})
    => []            # nothing is scanned at all

Same for `gh pr edit 12 --title "..."`. In v3.64.0 the old branch at
sensitive_content.py:762 appended `_Haystack(subject=command, text=command)` for
any `gh (issue|pr) (comment|create|edit)`, so a blocked term in the title was
DENIED. It is now ALLOWED and published. Pattern-level confirmation:

    old-pattern  new-pattern  command
    True         False        gh issue create --title "alpha-term"
    True         False        gh pr edit 12 --title "alpha-term"
    True         True         gh issue create --title t --body "alpha-term"

The comment's rationale ("a surface invoked with NONE of them publishes no text —
`gh pr review --approve` records an approval") does not hold for `--title`, which
always publishes text.

FIX: add the title/description spellings to `_GH_BODY_FLAGS`:

    _GH_BODY_FLAGS: Final[str] = (
        r"--body|-b\b|--notes|--desc(?:ription)?|--title|-t\b"
        r"|--body-file|-F\b|--notes-file"
    )

and add cases to `TestGhBodySurface` (tests/unit/handlers/pre_tool_use/
test_sensitive_content.py:1198) for `gh issue create --title "alpha-term"` and
`gh pr edit 12 --title "alpha-term"`. While there: `gh gist create -d '<term>' f.md`
(short form of `--desc`) is also uncovered.

---

### D2 — adding `install` to the relocation verbs false-denies an ordinary worktree dev loop

`handlers/pre_tool_use/worktree_file_copy.py:35-37` (`_RELOCATION_VERBS`,
`_RELOCATION_VERB_RE`) and `:133`

The verb test is a bare `re.search` over the WHOLE command and is not tied to the
path pair matched at `:145`. `install` is a common English word in
package-manager invocations, so any command that (a) names a worktree path three
segments deep and (b) later names a main-repo code dir now trips a TERMINAL deny
announcing catastrophic data loss.

Reproduced against the shipped handler (`matches()` result):

    True  | cd untracked/worktrees/wt-a/src && pip install -r requirements.txt && pytest tests/
    True  | cd untracked/worktrees/wt-a/app && npm install && npm run build -- --out src/
    False | cd untracked/worktrees/wt-a/src && pytest tests/        (identical minus "install")

The first command relocates nothing. It was ALLOWED in v3.64.0 (verbs were
cp|mv|rsync) and is DENIED now — and it is the normal "work inside a worktree"
loop this project tells agents to use. The new negative test at
tests/unit/handlers/test_worktree_file_copy.py:597-601 anticipates this class but
all three of its cases stop short of naming a code dir afterwards, so the hole is
not caught.

FIX: require the verb to be in command position rather than anywhere in the string:

    _RELOCATION_VERB_RE = re.compile(
        r"(?:^|[;&|]|\$\()\s*(?:sudo\s+)?(?:\S*/)?("
        + "|".join(_RELOCATION_VERBS) + r")\b",
        re.IGNORECASE,
    )

`install -m 644 ...`, `dd if=... of=...`, cp, mv and rsync all sit at a segment
head, so the existing positive tests keep passing; `pip install` / `npm install`
stop matching. Add the two commands above as negative cases.

---

### D3 — the git commit message exemption lets a real plan-dir scan through

`handlers/pre_tool_use/plan_number_helper.py:280-297`
(`_is_git_commit_message_mentioning_plans`), used at `:434`

The docstring claims "Requiring the last mention to be inside the message means
EVERY mention is." It does not: a mention BEFORE `git commit` is never examined —
only the position of the LAST mention is checked.

Reproduced (True = the exemption fires, so `_should_block` returns False and the
scan runs unguarded; PD below stands for the configured plan directory literal):

    True  | ls PD*/ && git commit -m 'prose PD here'
    True  | find PD -name PLAN.md; git commit -m 'why PD scans fail'
    False | git commit -m 'prose PD' && ls PD*/          (the case it does close)

That is exactly the bypass the docstring says it prevents, with the operands
merely reordered. Blast radius is small (a workflow nag, not a safety gate), but
it is a fail-open gap and the code asserts a property it does not hold.

FIX: require the FIRST mention to be inside the message as well —

    first_mention = command.find(plan_dir)
    if first_mention < git_match.start():
        return False
    last_mention = command.rfind(plan_dir)
    text_between = command[git_match.start() : last_mention]
    return re.search(f"[{_COMMAND_SEPARATORS}]", text_between) is None

---

### D4 — a dot pathspec skips the new guard-config commit gate entirely

`handlers/pre_tool_use/guard_config_commit_gate.py:121-128` (`_pathspec_covers`),
reached from `recorded_config_source` at `:105`

`_pathspec_covers` does a literal prefix comparison with no normalisation, so a
pathspec of `.`, `./`, or a `./`-prefixed config path is judged NOT to cover the
config: `recorded_config_source` returns None and the gate allows with no
context, never reading the config at all.

Reproduced (`recorded_config_source(command, CONFIG_RELATIVE_PATH)`):

    None          | git commit . -m x
    None          | git commit -m x ./
    None          | git commit -m x ./.claude/hooks-daemon.yaml
    working-tree  | git commit -m x .claude/hooks-daemon.yaml     (the spelling it catches)

`git commit . -m 'msg'` commits the working tree of everything below the cwd,
including a `.claude/hooks-daemon.yaml` that disables a handler. The gate's whole
deliverable is the RECORD, and for these spellings there is none.

FIX, in `_pathspec_covers`:

    normalised = spec.rstrip("/")
    if normalised.startswith("./"):
        normalised = normalised[2:]
    if normalised in ("", "."):
        return True          # a whole-tree pathspec carries everything
    return config_path == normalised or config_path.startswith(f"{normalised}/")

plus tests in tests/unit/handlers/pre_tool_use/test_guard_config_commit_gate.py
for the three missed spellings.

---

### D5 — the git switch force pattern over-matches `--force-create`, contradicting its own comment

`handlers/pre_tool_use/destructive_git.py:594-600`

The comment above the pair states the force test is "exact `--force` (never a
prefix, so `--force-with-lease` and a hypothetical `--foo` stay out)". The
checkout pattern implements that with `--force(?!-)`; the switch pattern does not
(`--(?:force|discard-changes)\b`), so `\b` matches inside `--force-create`.

Reproduced (`matches()`):

    True  | git switch --force-create foo
    False | git switch -c foo
    False | git checkout --force-with-lease origin main     (the checkout guard works)

`git switch --force-create` (the long spelling of `-C`) resets a branch ref; it
does not discard uncommitted working-tree changes, and git refuses it when local
changes would be lost. The user is denied with "discards every uncommitted
change" — a message about something the command cannot do. Worse, `git switch -C
foo` is ALLOWED, so the same operation is permitted or refused by which spelling
was typed.

FIX: `r"(?<!\S)--(?:force(?!-)|discard-changes)\b"`, plus a negative test for
`git switch --force-create foo`. If `-C` is genuinely meant to be blocked, give
it its own rule with an accurate reason.

---

## NON-DEFECTS (refactors, gaps, judgement calls)

### N1 — dead code left behind by the message-file extraction

sensitive_content.py `:271` `_GH_BODY_FILE_PATTERN`, `:274` `_STDIN_BODY_FILE`,
`:277` `_MAX_BODY_FILE_BYTES`, the `_BODY_FILE_ENCODING` /
`_BODY_FILE_DECODE_ERRORS` pair, and `:770-795` `_read_body_file` are
unreferenced anywhere in src/ or tests/ (verified by grep) now that
`_gh_body_file_haystacks` was replaced by `utils.message_files.read_message_files`.
Delete them; the shared reader owns this.

### N2 — the argv-injection fix ships with no test on either handler

post_tool_use/lint_on_edit.py:484-490 and pre_tool_use/staged_lint_gate.py:293-299
(Plan 00412 class 7). No test exercises the new behaviour: grep for
`command_parts`, `shlex.join`, `_FILE_PLACEHOLDER` and "re-tokenis" across tests/
returns nothing, and test_lint_on_edit.py changed by 2 lines in this bundle.
Step 10 requires tests alongside every handler change, and this is a security fix
whose effect is invisible at runtime (a path with a space silently linted two
missing files before; nothing asserts it no longer does). Add one test per
handler: file path `my file.py`, and file path `x.py --config /tmp/evil.toml`,
must each arrive as a single argv element.

### N3 — magic string, and embedded placeholders silently stop working

staged_lint_gate.py:297 hardcodes the `{file}` literal while lint_on_edit.py:46
names it `_FILE_PLACEHOLDER`; the project's own declared-invariant-pairs
reasoning (worktree_file_copy.py:28-34) argues for one shared constant.

Separately, both handlers moved from `.replace()` to a token-equality
substitution, which drops support for a placeholder embedded in a larger token
(`--path={file}`). Every built-in strategy uses a standalone placeholder so
nothing ships broken, but lint_on_edit accepts per-language command OVERRIDES
from hooks-daemon.yaml (`_get_lint_commands`, :317-331); such an override would
now pass the literal placeholder to the linter, exit non-zero, and DENY the
user's edit with an unactionable message. `part.replace(_FILE_PLACEHOLDER, path)`
inside the comprehension keeps both the one-argv-element property and the
embedded form.

### N4 — the shared message reader misses the attached short-option form (pre-existing)

utils/message_files.py:36 — `MESSAGE_FILE_PATTERN` requires whitespace or `=`
after the flag, so `git commit -Fmsg.txt` (valid git) names a file that is never
read, while `git commit -F msg.txt` is scanned. Both former private copies had
this gap, so it is not a release regression; now that the reader is
single-sourced, one change fixes both sensitive_content and
github_auto_close_keywords. Also `path.stat()` at `:88` sits outside the `try`
guarding `read_bytes()`, so the same unlink race the comment at `:93-97`
describes can still raise out of the reader.

### N5 — ask_user_question_blocker mode handling

`getattr(self, "_mode", MODE_STRICT)` is repeated at `:204`, `:211`, `:286`,
`:397`; a `_current_mode()` helper would carry the default once. More
substantively, an unrecognised mode value is silently treated as strict — a
typo'd `unattendeed` in a cron-driven project restores exactly the hang the mode
exists to prevent, with no log line. Validate the option against the three
constants and log loudly on an unknown value.

### N6 — the guard-config gate resolves the repo differently from its sibling

guard_config_commit_gate.py:173-212 reads HEAD and the working tree from
`ProjectContext.project_root()`, while `sensitive_content._staged_content_haystacks`
deliberately runs "in the repository the command targets (the hook's cwd, else
the project root)". A `git commit -a` issued inside a worktree or a nested repo is
therefore judged against the MAIN checkout's config: it can both miss a real
weakening and report one this commit does not carry.

### N7 — worktree_file_copy guidance no longer matches the code

The Rule text (worktree_file_copy.py:54) and `get_claude_md` (:185) both still say
cp/mv/rsync only, while the handler now also denies `install` and `dd`. The
generated R-WORKTREE-FILE-COPY row in CLAUDE.md inherits the stale text, so an
agent cannot predict the deny from the published rule. Update both when D2 is fixed.

### N8 — priority band (noted for the record, no change requested)

`Priority.GUARD_CONFIG_COMMIT_GATE = 49` sits in the workflow band (36-55) while
the handler carries HandlerTag.SAFETY. Given it is non-terminal, ALLOW-only and
must run after the gates that can DENY, the placement and the rationale at
constants/priority.py:308-312 are right.

---

## Positive observations

* utils/message_files.py is the right fix for D-PUB-2: one reader, both handlers,
  and `MessageFile.path` means a deny can name the file without quoting the line,
  preserving the secret-word disclosure contract.
* `validate_eslint_on_write._resolve_interpreter` replaces a PATH prepend into the
  GUARDED project's node_modules/.bin with an explicitly named binary, and the
  docstring is honest that the fallback and the wrapper are still tree-supplied.
* tdd_enforcement's `strategy.is_excluded_source_file` veto is on the protocol and
  all twelve strategies — no if/elif on language names anywhere in this diff.
* destructive_git's three tables stay index-aligned, and the narrow spellings hold:
  `--expire=90.days.ago`, `git gc`, `git gc --auto`, `--force-with-lease`,
  `git switch -c`, `git checkout -b`, `git checkout main` all verified unblocked,
  and `git status && grep -f patterns notes.txt` is not swept in.
* DATA_SINKS moved from curl_pipe_shell to utils.shell_segmentation byte-identical
  (verified: no additions, no omissions), so eight other handlers inherit the
  allowlist without changing this handler's semantics.
* No debug code, TODO/FIXME, or QA suppressions introduced; the one added `# nosec`
  carries a specific justification.

## Verdict

REQUEST CHANGES. D1 (a leak guard that scanned `--title` in v3.64.0 and does not
now) and D2 (a terminal deny on a `pip install` inside a worktree) are release
blockers. D3-D5 are smaller but each is a contract the code does not keep.

Probe scripts kept as evidence: untracked/scratch/probe_git.py (destructive-git
spellings) and untracked/scratch/old_sc.py (the v3.64.0 sensitive_content used for
the D1 before/after).
