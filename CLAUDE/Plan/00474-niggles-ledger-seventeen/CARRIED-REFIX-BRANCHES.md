# Entries carried from the six dropped re-fix branches

These ledger entries existed only on branches of ledger 00466's cleanup that were
judged too tangled to merge (assessment:
`CLAUDE/Plan/00466-niggles-ledger-sixteen/subagent-reports/260930-large-branch-assessment-sonnet.md`).
The branches are dropped, so a "Remedied" status below means remedied on that
branch only. Every entry here is OPEN on `main`. Write-ups are verbatim from the
branch's NIGGLES.md where one existed.

## Branch `worktree-upgrade-scripts`

### N108 — `destructive_git` denies a git call split across lines between its options and its subcommand

**Status on the branch**: ⬜ Open. **On main**: open.

**Found by upgrade-scripts round 16b** (`260926-upgrade-scripts16b-opus-5-5.md`
in Plan 00464, "Still open" item 7b). A git call written with a line
continuation after its global options, for example `git -C "$dir" \` with the
subcommand on the next line, is read by `destructive_git` as a git call whose
subcommand it cannot find, and is denied. The same call on one line is
allowed. Scripts wrap long git calls this way, so a harmless read in a script
the walk follows is refused, and the agent is told to rewrite code that is
correct.

**Why:** the walk that finds the subcommand does not join a backslash-newline
between the options and the subcommand before it looks for the subcommand.

**Remedy:** join backslash-newline continuations the way bash does before the
subcommand is looked for, in the shared walk rather than in `destructive_git`
alone. Pin both spellings (continuation after `-C DIR`, after `-c k=v`, and
after `--git-dir=…`) with one allowed read and one denied destructive
subcommand each, so the fix cannot turn the denial into an allow for a
destructive call.

### N121 — `secret_file_guard` and `flaggable_content_channel_guard` deny ordinary review commands that name nothing protected

**Status on the branch**: ⬜ Open. **On main**: open.

**Found by upgrade review 12** (`260926-upgrade-review12-opus-5-5.md` in
Plan 00464, L-R12-8, and its L13 row). It is main's code, in the same class
as review 11's L13 and as N101. Three shapes of false positive:

- `grep -n '^class .*Handler' <file>` is denied as R-SECRET-BASH-MENTION.
  The regex token `.*Handler` is read as a path spelling and matched the
  protected glob `.vault-pass*`.
- `grep -a '…Error…' <scratch>/m3.out` is denied as
  R-FLAGGABLE-CONTENT-CHANNEL, naming `tests/fixtures/cyber-flag/**`, a path
  the command never mentions.
- R-SECRET-EVALUATION-ERROR with `TooManyToEnumerateError`: on
  `grep -n "trap " …/scripts/install/*.sh` in review 12, and again in the
  following round on ordinary Bash commands and on Write content with
  `$P/$d/...` paths while `untracked/scratch` held more than 600k files.

Each denial stops a read-only command that names no protected path, and the
agent is told to route around a guard that did not find anything.

**Why:** the guards treat a regex argument to `grep` as a shell word that
could expand to a path, and the enumeration of what a glob or variable path
could expand to is bounded by the size of the tree it walks, so a large
scratch directory turns an ordinary command into an evaluation error.

**Remedy:** reproduce all three shapes against main's handlers. Do not treat
a `grep`/`rg` pattern operand as a path. Establish why the flaggable-content
channel names a path the command does not contain. Make the enumeration's
bound independent of unrelated tree size (for example, match globs against
the protected patterns instead of listing the directory), keeping fail-closed
where a word really could expand to a protected name. Pin each shape with a
test, alongside N101's.

## Branch `worktree-d-00421`

### N170 — `secret_file_guard`'s secret-meta and `git rm --cached` exemptions let a second command read a protected file

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 4, D-RULE check (finding SH1, graded BLOCKER),
reproduced in memory against main's source. All of these were ALLOWED while
plain `cat <protected>` was denied:

- `bin/hooks-daemon secret-meta x & cat <protected>`
- `bin/hooks-daemon secret-meta $(cat <protected>)`, and the backtick form
- `git rm --cached foo & cat <protected>`

**Why:** `is_exempt_invocation` judged "one command" with
`_COMMAND_SEPARATORS`, which has no lone `&`, and looked only for `<(` among
substitutions. Its helper and `git rm --cached` branches then returned True on
the head alone, without looking at redirections or the rest of the words. So a
protected file's contents could reach context in one command.

**Remedy:** an exemption now applies only when the WHOLE command is that one
invocation. The new `_is_one_plain_command` reuses the module's existing shell
primitives (`_shell_words`, the punctuation-aware shlex reader the
encrypted-target exemption uses, and `_carries_substitution`). It refuses any
operator token (separator, lone `&`, pipe, redirection, subshell), a newline,
any command or process substitution outside single quotes, and quoting that
does not parse. The single leading `cd <dir> &&` strip also refuses an
operator character in its target. RED on `85112da98`:
`TestBash::test_an_exemption_covers_only_the_whole_command` (11 of 12 cases
failed; the consumer `& cat` case was already denied by the flag-position
check). `test_a_whole_exempt_invocation_is_still_allowed` pins the plain
forms, including `cd /proj && …`, `git -C /repo rm --cached` and `time`.

### N171 — `scan_scope.walk_files` skipped a directory it could not list, so every pinned walker reported it clean

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 4, shared finding S-a.

**Why:** `os.walk` with no `onerror` drops a directory it cannot list and
carries on, so each of the seven walkers pinned by N26 reported the files in
it clean without reading them.

**Remedy:** `walk_files` passes an `onerror` that raises the new
`scan_scope.WalkError`. A missing root still yields nothing, and
`vacuous_scan_failure` reports that. The test patches `os.scandir` to raise,
because a chmod-based test proves nothing when tests run as root. RED on
`7d0e63075`: `test_an_unreadable_subdirectory_fails_the_walk`.

### N172 — An `ImportError` of the shared secret-term rule switched the term rule off in the batch checks

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 4, shared finding S-b.

**Why:** `check_git_history.resolve_term_matcher` and `resolve_secret_terms`
caught `ImportError` and returned a matcher that never matched and no terms.
Run by an interpreter without the daemon package, the history sweep, and
`check_git_blobs` through it, reported clean without checking any term.
`check_sensitive_content` had the same two fallbacks.

**Remedy:** each of the three checks loads the shared module through one
`_term_rule()` that raises its `ConfigError`, which each already reports as a
failing finding. The same round made all three read every configured word
list through `secret_redaction.resolve_secret_word_list_paths`. RED on
`c87ac8c0c`: `test_an_unimportable_matcher_is_a_config_error` and
`test_an_unimportable_term_rule_fails_the_run`.

### N173 — A direct write to `.git/config` could erase the last-known-good loaded-before marker

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 fix round 5, while closing review-4 D1r. The marker
that tells a degraded daemon "a config loaded here once" apart from "none
ever did" was a git config key, `hooksdaemon.<dir>.lastKnownGoodWrittenAt`.
D1r denied the `git config` commands that erase it, but a Write/Edit of
`.git/config`, a redirect into it, `rm` or `mv` reached the key without
naming any protected path, and no guard judged them.

**Why:** a git config key is not a path, so the WRITE_ONLY mutation check,
which covers every write route to a protected FILE, could not see it. A
second, command-shaped check for one key covered only the `git config`
spellings.

**Remedy:** the coordinator's preferred option. The marker is now a file,
`<git common dir>/last-known-good-marker-<digest of the snapshot directory>`,
written atomically by `config.last_known_good.write_marker` and located by
`marker_path` (`git rev-parse --path-format=absolute --git-common-dir`). It is
still outside the snapshot's directory, so review-3 D1 holds, and linked
worktrees keep one marker each in the shared common directory. A second
shipped WRITE_ONLY entry, `last-known-good-marker-*`, protects it through the
code that already protects the snapshot: a Write/Edit, a redirect, `rm`, `mv`,
`truncate`, a `cp` onto it and a glob `rm` are denied, and a read is allowed.
The D1r `git config` key check, `bash_git_config_key_write`, is deleted,
because nothing is held in git config any more. A basename glob also covers
layouts a `.git/config` path glob would miss, such as a submodule's
`.git/modules/<name>/config`. RED on `acddbb204`: 10 cases of
`TestTheLastKnownGoodSnapshot::test_a_bash_write_move_or_delete_of_the_marker_is_denied`
and `test_a_write_or_edit_of_the_marker_is_denied` failed, and
`test_last_known_good.py` could not import `marker_path`.

### N174 — A path built from a name escaped the directory it was joined onto

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 fix round 5d. `check_authored_path_containment` began
deriving write helpers from the package, and found twelve CLI commands whose
argument reaches a write with no containment test. Seven of them build the
path from a NAME: an approval key, an agent name, a capture URL, the two
report versions, and a routine's year. The same derivation, matching a helper
by name, also reached `SubagentCacheAggregatorHandler.record`, which builds its
sidecar path from the payload's session and agent ids.

**Why:** each helper joined the name onto a directory and wrote there. Some
sanitised first, but sanitising kept `.`, `..` and a leading `-`: a session id
of `..` put the sidecar one level up, a `--from-version` of `-1.0.0` named a
report directory, and a store whose derivation ever changed would have written
wherever it pointed. Round 5e also found the detector itself too generous.
`relative_to` is lexical, so `Path("tree/../x").relative_to("tree")` succeeds,
and a test against a root the argument chose (`p.relative_to(p.parent)`) was
counted as containment.

**Remedy:**

- `utils/path_component.require_path_component` refuses a name that is empty,
  `.`, `..`, holds a separator or a NUL, or starts with `-`.
- Each helper applies it to the name, then tests the joined path with
  `resolve().relative_to(<directory>.resolve())`. The helpers are
  `OneShotApprovalStore.path`/`record`/`consume`, `deployed_agent_path` with
  `deploy_agent`/`remove_agent`, `write_capture`, `require_report_versions` in
  both report commands, `ledger_path`/`append_event`, and the aggregator's
  `_sidecar_dir`/`record`.
- `run-routine` refuses a routine folder that resolves outside the routines
  tree.
- The detector counts a containment test only on a normalised receiver
  (`resolve()`, `realpath`, `abspath`, `normpath`, or a variable every
  assignment of which is one). It no longer counts an origin that the root
  argument also carries.

RED on `5241b68a2`: 29 new tests fail, and 7 suites cannot import the new
module. Mutant M1 accepts every name and every output target in the two new
utilities. Under M1, 40 tests fail, among them every per-helper name test.

### N175 — A YAML option named after a handler's internal attribute overwrote it, safety guards included

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 fix round 5f, deciding review-4's step 7 entry on the
`_NOT_OPTIONS` table in `test_last_known_good.py`. That table named the
`__init__` attributes (`formatter`, `rule`, `registry`, `rules_by_id`, ...)
that are "not options", so that the option-classification test would skip
them.

**Why:** `registry.apply_handler_options` ran `setattr(instance, f"_{key}", value)` for every key under a handler's `options:`. Nothing separated an
option from internal state, so `options: {rule: null}` on `destructive_git`
replaced the guard's rule object, and `formatter` replaced its formatter. The
same loop is on `main`. The table only described the attributes; it protected
none of them. It was also wrong in one place: `tdd_enforcement.test_locations`
is a documented option, and the table listed it as internal.

**Remedy:**

- `Handler.declared_options` is a class-level frozenset of the keys a
  handler reads. `apply_handler_options` sets only those, and returns the rest.
- `register_all` records a handler's undeclared own keys in pass 1, logs them
  at WARNING, and exposes them as `registry.undeclared_options`. A key that
  reaches a child through `shares_options_with` is charged to the parent.
  `health` lists them and exits 1, and the session-start alert names each
  handler and key. `config-validate` reports each one as a warning that names
  `handlers.<event>.<name>.options.<key>`. It is a warning because the key is
  never applied, and an upstream option removal must not put a client daemon
  into degraded mode.
- `workspace_root` is set by the registry directly. It is no longer merged
  into every handler's options.
- 61 handlers declare their options. The declarations come from each
  handler's `__init__` and `getattr` reads, its `HANDLER_REFERENCE.md` table,
  this repo's config, the example config and the generated config.
- The `_NOT_OPTIONS` table and its `__init__` scan are gone. The
  classification test now checks `declared_options` against
  `PROTECTIVE_HANDLER_OPTIONS` and `NOT_CARRIED`, and checks the reverse too.
  Declaring surfaced four options nobody had classified. `test_locations`,
  `allow_plain_hash` and the two `history_*` keys are now in `NOT_CARRIED`.
- `test_declared_options_cover_shipped_options.py` fails when a shipped
  config, a doc YAML example or a reference option table names an undeclared
  option. It found `budget_exhaustion_detector.exclude_paths` documented but
  never read, so that row is removed from the reference.

RED: on `f083f5b1a` a registration with `options: {formatter: HOSTILE, rule: null}` leaves `destructive_git` with `_formatter == "HOSTILE"` and `_rule is None`. Mutant M1 restores the blind `setattr`, and 3 tests fail. Mutant M2
drops `test_locations` from `tdd_enforcement`, and 3 tests fail. Mutant M3
stops recording undeclared keys, and 5 tests fail.

### N228 — The secret-meta, `git rm --cached` and consumer exemptions read the command with `str.split()`

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 5, D-RULE check (finding SH2, graded BLOCKER).
Shared with main.

**Why:** the head, subcommand and flag tests ran on `str.split()` plus
`strip("\"'")`, not on the words the shell delivers. So each of these was
exempt:

- `git rm --cached '--pathspec-from-file'=<secret>`
- `git rm --cached --pathspec-from-fil\e=<secret>`
- `git rm --cached --pathspec-from=<secret>` (git accepts the prefix)
- `ansible-vault 'view' ...`, `vi''ew` and `de\crypt`

The pathspec forms print the file through git's `did not match` error, and
`view`/`decrypt` print the decrypted vault.

**Remedy:** `is_exempt_invocation` reads the command with
`_literal_shell_words`: the shared `shlex` reader, used only when nothing in
the command expands (no `$`, backtick, glob, brace, comment, or backslash
inside double quotes). Each shape then takes a closed allowlist of options,
spelled in full:

- `git rm`: `--cached`, `--dry-run`, `--quiet`, `--force`,
  `--ignore-unmatch`, `--sparse` and clusters of `-rnqf`, after `-C`, `-c`,
  `--no-pager`, `--git-dir` or `--work-tree`. None of those values may
  mention a protected path.
- `secret-meta`: one path and `--project-root`.
- ansible consumers: a disclosure subcommand anywhere among the non-option
  words denies. `edit` joins `view` and `decrypt`, because it hands the
  decrypted text to `$EDITOR`.

A test runs each shape under bash, with PATH holding only recording
scripts, and checks that the argv bash delivers equals the exemption's
reading. RED on `59d44d08f`: 33 cases of `TestExemptionsReadTheShellsWords`.
Six of them failed only because `_literal_shell_words` did not exist yet.

### N229 — The consumer exemption skipped every word starting with `-`, so a path inside an option value was never judged

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 5, D-RULE check: SH3 (shared with main) and B1
(this branch's snapshot floor).

**Why:** `_paths_only_in_flag_position` skipped any word starting with `-`.
So these were exempt while the spaced forms were denied:

- `ansible localhost -m slurp --args=src=<secret>`
- `ansible-playbook -e@<secret>`
- `ansible-vault encrypt ... --output=<snapshot>`
- `ansible localhost -m copy --args=dest=<snapshot>`

Separately, the mention scan did not see a path after `@` at all, so
`ansible-playbook -e @<secret>` and `curl -d @<secret>` mentioned nothing.

**Remedy:** only a recognised path flag's own value is exempt. Every other
word, option words included, faces the mention scan. That scan now also
reads the text after the first `@` and a value attached to a short option
(`-f<file>`, `-cf<file>`), through
`secret_file_matching._embedded_path_candidates`, which is bounded to linear
work per token. The snapshot route uses the same exemption, so B1 closes
with it. RED on `59d44d08f`: 15 cases of `TestExemptionsJudgeOptionValues`,
`test_a_re_spelled_word_or_an_option_value_gets_no_exemption` and
`test_a_consumer_option_value_naming_the_snapshot_is_not_exempt`.

### N230 — `secret-meta --project-root <dir>` read `allow_plain_hash` from a config the agent could write

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 5, D-RULE check (finding SH4). Shared with main.

**Why:** `cmd_secret_meta` loaded the config, and the HMAC key, from
whatever `--project-root` named, and the guard exempts that command shape.
An agent could write `<dir>/.claude/hooks-daemon.yaml` with
`allow_plain_hash: true` and get the exact size and plain sha256 of any
protected file. The docstring said an agent could not self-grant that.

**Remedy:** the config and the key always come from the project the CLI
resolves for itself (`get_project_path`, anchored by the wrapper). A
`--project-root` that resolves anywhere else gets the non-disclosing
default. RED on `59d44d08f`:
`test_a_different_project_root_never_grants_the_plain_hash`.

### N231 — A secret word list that exists but cannot be read gave no terms, so a scan through it passed

**Status on the branch**: ✅ Remedied. **On main**: ✅ Fixed (branch `worktree-n231-wordlist`, not yet merged)

**Remedy on main:** A word list that exists but cannot be read (a directory in
its place, a dangling symlink, or a read error) now raises
`SecretWordListUnreadableError` instead of giving no terms, and is never
cached as empty; an absent list is still inert. `sensitive_content` denies
the write with a reason that names the problem and no term. The two batch
checks that scan with the terms (`check_sensitive_content`,
`check_git_history`) fail the run with a config error. The router, front
controller and blocking-response logs write a withheld placeholder, payload
capture is skipped, the model-fallback snapshot is not written, and the
`hooks-daemon` commands that scrub output stop with exit 1. There is no
`check_git_blobs` or `require_active_secret_terms` on main; the details below
describe the dropped branch.

**Found:** Plan 00421 review 5, CODE check (finding M2). Shared with main:
main's `secret_redaction.load_secret_terms` also returns `()` on any
`OSError`.

**Why:** `load_secret_terms` treated "cannot be read" like "absent", and
returned no terms. `check_git_history` and `check_sensitive_content` scanned
with those, and `check_git_blobs` recorded `unreadable` in its cache
fingerprint and scanned on. `sensitive_content` judged every write against
no terms. Each reported clean without checking a term.

**Remedy (this round):** `load_secret_terms` and `get_cached_secret_terms`
raise the new `SecretWordListUnreadableError` for a list that exists but
cannot be read, and are never cached as empty. An absent list stays inert.

- The three batch checks turn it into their `ConfigError`, so the run fails.
  `check_git_blobs._word_list_identities` raises too, rather than
  fingerprinting it.
- `sensitive_content` reads through the new `require_active_secret_terms`.
  It is SAFETY+BLOCKING, so the chain denies the call.
- `model_fallback_detector` writes no snapshot, and says so in its
  advisory.
- `hooks-daemon skill-scan` stops with exit 1.

The tests patch `Path.read_text` or put a directory in the list's place,
because chmod proves nothing as root. RED on `59d44d08f`:
`test_a_list_that_exists_but_cannot_be_read_raises`,
`test_the_chain_denies_when_the_configured_list_cannot_be_read`,
`test_an_unreadable_word_list_fails_the_run`,
`test_an_unreadable_word_list_is_a_config_error` and
`test_a_word_list_that_exists_but_cannot_be_read_fails_the_scan`.

**Closed by later rounds:** every other leak vector now reads through
`require_active_secret_terms` and fails closed on the error. Payload capture
is skipped, the router, front-controller and blocking-response logs write a
withheld placeholder, and `bug-report`, `issue-report` and `debug_info`
refuse. Round 7c (N246) made the same hold for an unreadable ADDITIONAL list
on a healthy daemon, and for a config that cannot load.

### N242 — A quoted grep pattern starting with `.*`, and a `python -m` module name, were denied as path mentions

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 6 (shared, minor), and hit repeatedly in
ordinary work. Shared with main.

**Why:** the mention scan read `.*get_active` as a glob that could name a
dotfile such as `.vault-pass…`, and `is_grep_pattern_only_mention` refused
any command containing `*`, even inside quotes, so the grep-pattern
exemption never applied. `python -m claude_code_hooks_daemon.utils.secret_redaction`
was judged as a glob over the dotted text, which `*.secret*` matches, though
Python only ever opens `claude_code_hooks_daemon/utils/secret_redaction.py`.

**Remedy (Plan 00421 round 7c, minimal because small-a also changes this
area):**

- The grep exemption accepts a glob character only where bash leaves it
  literal: it reads the words through `_literal_shell_words`, which refuses
  an unquoted one. An unquoted `.*foo` can expand to a dotfile, and every
  expansion past the first becomes a FILE operand, so it stays denied. A
  protected FILE operand is still denied.
- `_without_import_module_paths` rewrites a `python -m a.b.c` argument to
  `a/b/c.py` before the scan, only for one plain, unquoted command whose head
  is a bare `python`, `python3` or `python3.N` followed by value-less options
  and `-m`. A second command, a function, a head with a `/`, an assignment
  prefix or an option with a value leaves the text as written.

Bash-differential tests show bash hands grep the quoted pattern unexpanded
with matching dotfiles present, expands the unquoted one to the protected
name, and that `python -m pkg.secret_mod` runs `pkg/secret_mod.py` and not a
file named `pkg.secret_mod`. RED on `0e0098de2`: six cases in
`TestAQuotedGrepPatternIsNotAPath` and `TestAPythonModuleIsJudgedAsItsFilePath`
(`tests/unit/utils/test_secret_file_matching.py`).

### N243 — A consumer exemption matched the head's basename, so a self-written `./ansible-playbook` received the protected path

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 review 6, both roles. Shared with main: main compared
`head_base` with `consumer.command` too.

**Why:** `is_exempt_invocation` stripped the head to its basename before
comparing it with each allowlisted consumer. `./ansible-playbook --vault-password-file <protected> site.yml` and `untracked/x/ansible-playbook …` were exempt, and bash runs the file at that path, which the agent can
write. No obfuscation was needed.

**Remedy (Plan 00421 round 7a, coordinator ruling):** a consumer is exempt
only when the command word is exactly its configured bare name, with no `/`.
That is the rule bare `git` already follows. Nothing in the same command can
rebind the word, because a function, alias, `hash`, `PATH` assignment,
`source` or `eval` needs a second command or an assignment word in front of
the head, and either voids the exemption. `PATH` itself is trusted, a
residual recorded in `CLAUDE/Security/FailOpenBoundaries.md`. The cost is
that `.venv/bin/ansible-playbook …` is no longer exempt, which is the
fail-closed direction. RED on `dda7be6fc`, each shape run under bash with a
recording script at every place bash could go:
`TestExemptionsFollowWhereBashGoes::test_a_consumer_is_exempt_only_as_the_bare_word`
(`dot-slash-head`, `relative-path-head`).

### N248 — `scripts/debug_info.py` never initialised `ProjectContext`, so it never applied the project's word lists

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 fix round 7a, while routing the scrubs through one
resolution. Shared with main: main's `debug_info.py` has the same lookup.

**Why:** `_secret_terms` called `require_active_secret_terms`, which reads
the project through `ProjectContext`. This script is a standalone process
that never initialises it, so the lookup returned `()` on every run and the
report was scrubbed of paths and hostname only. Only a test that injected
lists in-process ever saw terms applied.

**Remedy (Plan 00421 round 7c):** `_secret_terms` calls
`secret_redaction.project_secret_terms` with this project's root and config,
the same resolution every sink uses (N246). Coordinator ruling (reversible):
on a bare interpreter the config model cannot be imported, so the script
REFUSES. It prints nothing that could carry a term, not even a path, and it
prints the remedy for the missing venv. A util module that cannot be found
or loaded refuses the same way, so the "NOT REDACTED" and "Secret word list
not applied" banners are gone, along with their two error-hiding exclusions.
RED on `0e0098de2`: `test_an_additional_only_term_is_redacted` and
`test_a_bare_interpreter_refuses_and_prints_no_path` in
`tests/unit/test_debug_info.py`.

### N250 — `remote-docs` captured a page UNSCANNED when the sensitive-content scanner could not load

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found:** Plan 00421 round 7c, while routing the word lists through one
resolution (N246). Shared with main: main `84afc8804` has the same code.

**Why:** `remote-docs add` and `refresh` write a fetched page straight to
disk, so the `Write`-tool hook never sees it and the CLI injects the
`sensitive_content` handler's own scanner. When that handler could not be
built (a config that would not load, an import failure), the capture went
ahead UNSCANNED with only a stderr warning, backed by an error-hiding
exclusion. Two more routes had the same effect. An unreadable word list
raised out of the write as a traceback. A relative
`additional_secret_word_list_paths` entry was resolved against the cwd,
because the CLI never initialises `ProjectContext`, so from any other
directory the list was missing and read as no terms.

**Remedy (Plan 00421 round 7d):** coordinator ruling (reversible),
consistent with N246: a config or scanner that cannot load REFUSES the
capture. `_sensitive_content_guard` raises `_ContentGuardUnavailableError`,
naming the config path or the list and the error type only. `add` and
`refresh` build the scanner before the config is read for anything else,
and exit 1 without fetching or writing anything, the index included.
Every list, main and additional, is resolved against the project root and
read once while the scanner is built. A list that turns unreadable after
that makes the scanner return a refusal reason, never clean. The
error-hiding exclusion is removed. RED on `9adcd9db6`: six cases in
`TestAnUnloadableScannerRefusesTheCapture`
(`tests/unit/remote_docs/test_cli_remote_docs.py`).

## Branch `worktree-plan-464-commit-gate-repo`

### N119 — The walk re-walks every `eval` text three times, so an `eval` chain costs 3^depth walks

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the Plan 00464 landing merge.** Main's
`test_safety_handlers_hostile_input_performance.py::TestCombinatorialSmallInputShapesStayLinear::test_bash_command[deep_eval_nesting]`
failed on the Plan 00464 branch: `enforce-project-containment` cost grew
125-190x for an 8x input. In `utils/git_command_target.py` the walk ran every
literal `eval` text three times: `_eval_effect` in the survey pass,
`_eval_effect` again in the walking pass, and `_walk_shell_text` for the
commands it runs. Each of those walks did the same to every `eval` inside
it, so walks grew 3^k until `MAX_SHELL_TEXT_DEPTH` (4) stopped the effect
walks: `"eval " * 20 + "true"` cost 1,417 walks, each re-lexing its text.

**Remedy:** `_run_text_once` remembers each shell-text walk for the rest of
one walk, keyed on the text, depth, shell-text count, every field of the
start shell by value, the disk and script budget it shares (by identity and
state), the script being read and the visitor. A walk is kept only when it
changed neither shared object, so answering from it skips nothing.
`_eval_effect` walks with the walk's own visitor, so its walk and the walk
of the text's commands are one walk when they start alike. `_shell_alias`
opens a walk cache too. The chain now costs depth + 1 walks, and the
hostile test's ratio is about 9x. Before any code changed, a verdict fixture
(`tests/fixtures/git_command_target_verdicts.json`) recorded every
`git_command_target` answer and the `project_containment` and commit-gate
verdicts for 1,245 harvested and 3,188 generated commands. The fixed walk
matches it exactly. Tests: `test_git_command_target_eval_walks.py`
(walk counts, key coverage and fresh-versus-remembered answers) and
`test_git_command_target_verdict_equivalence.py`.

## Branch `worktree-n466-small-a`

### N124 — `secret_file_guard` reads a grep/rg regex argument as a path and denies it

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a fixer.** `grep -n "def .*repair\|uv" f`,
`grep -v '^tests/.*:.*#'` and `grep "^tests/.*test_.*\.py$"` were each denied
as a protected-path mention: the guard glob-matched the regex text against the
default `.vault-pass*` pattern, although grep never opens its pattern.

**Remedy:** classify the PATTERN argument of grep/rg/awk as search data, not a
path; genuine path operands and anything unclassifiable still fail closed; no
new allowlist entries.

**✅ Remedied on `worktree-n466-small-a`.** New
`utils/search_pattern_arguments.strip_search_pattern_arguments` replaces the
pattern word of each `grep`/`egrep`/`fgrep`/`rg`/`awk` simple command with
`''`, and only when it is proven data: no substitution or heredoc anywhere,
the head is the searcher itself (not `env`/`sudo`), every earlier option is
one the per-tool table knows (so `-f`, `-A 3`, `-g` cannot shift the slot),
the word is literal (quoted, or bare with nothing the shell expands), and an
awk program names nothing that opens a file or runs a command (`getline`,
`system`, `ARGV`, `<`, `>`, `|`, ...). `secret_file_guard` re-runs its WHOLE
Bash verdict on the stripped text and allows only when that finds nothing, so
every operand, `-f` file and `-g` glob is still judged by the unchanged scan.
RED: 6 of the handler cases in `TestSearchPatternArgumentsAreNotPaths`; the
module has its own 47 cases in `tests/unit/utils/test_search_pattern_arguments.py`.
Mutations proven red: dropping the awk-program vetting (2 fail), and letting
`-f` leave the positional slot as a pattern (`grep -f patterns.txt <protected>`
fails). Release note 142.

**Round 4 (B1, `0fcda9c4d`):** a pattern attached to its option (`-eX`,
`-e'X'`, `--regexp=X`) was blanked to `''`, which bash hands grep as a bare
`-e` that takes the NEXT word, a file, as its value. It is now blanked to
`_`. `test_blanking_never_changes_the_argv_bash_builds` re-splits the result
with `shlex` and checks the argv shape is unchanged. Release note 148.

### N125 — `quarantine_artefact_read_guard` refuses a plain `grep -l` over subagent transcripts as too many to enumerate

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a fixer.** `grep -l x ~/.claude/projects/-workspace/*/subagents/*.jsonl`
(and the `rg -l` form) was denied with `TooManyToEnumerateError`, as was
`grep -aoE "[a-z_/]+\.py:[0-9]+" out.txt`, though neither can read a DETAIL
artefact.

**Remedy:** decide from the glob's own literal parts whether it could ever match
`*-opus-security-DETAIL*`; enumerate or deny only when it could, or when that
cannot be decided; fail closed stays intact.

**Root cause, and why literal parts alone do not clear the reported glob.** The
final component `*.jsonl` CAN name an artefact (`x-opus-security-DETAIL.jsonl`),
so it genuinely needs a look at the disk. The refusal came from where the walk
started: `_expand_glob_token` rooted every absolute glob at `/`, where two
wildcard segments are refused as a filesystem-wide walk, though the first
wildcard sits five directories down. The regex case was the second cause: a
relative token was expanded against the daemon's own cwd, which is `/`, and its
final component was never compared with the patterns at all.

**✅ Remedied on `worktree-n466-small-a`.** `secret_file_matching`:
`_patterns_a_glob_could_name` keeps only the patterns a glob's final component
can intersect (`_globs_can_intersect`), keeping every pattern that is anchored
(`/`) or recursive (`**`) and every pattern when the component itself carries
`**`; a glob that reaches none is not enumerated. `_expand_glob_token` walks an
absolute glob from its longest literal directory prefix, so a wildcard that
really starts at `/` keeps the refusal (`cat /*/*/t-opus-security-DETAIL*` is
still denied). RED: 2 of the four handler cases in `TestBashGlobTokenExpansion`;
6 unit cases in `test_secret_file_matching.py`. Mutations proven red: no literal
prefix (2 fail), every pattern reachable (4 fail). Release note 143.

### N129 — An abbreviated grep long option hid the file operand from the secret guard

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-RULE review (S2), shared with main.** GNU
`getopt_long` accepts any unambiguous abbreviation, so `--fil=/dev/null` is
`--file=`. That turns the word the exemption reads as the pattern into a
FILE. `is_grep_pattern_only_mention` skipped unknown long options, so
`grep --fil=/dev/null <protected>` was allowed on main.

**Remedy (small-a round 2, `d5e1a3849`):** both the main exemption and
N124's stripper consult one option table,
`search_pattern_arguments.options_are_classifiable`. An option that is
unknown, abbreviated, or a boolean given a value leaves the command
unclassified, so the deny stands. There is no abbreviation table. RED: 4
handler cases and 7 module cases. Release note 142.

### N130 — Glob and directory walks answered "nothing here" when they could not finish

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH (BLOCKER 2, MAJOR 3) and D-RULE (F4) reviews,
shared with main.** Four defects, each of which made the walk fail open:

- `bounded_recursive_glob` walked a non-recursive pattern with plain,
  unbounded `Path.glob`.
- It pruned `node_modules`, `.git` and similar directories.
- It compared the root refusal against the spelling `/`, so `/usr/..` and
  `/proc/self/root` were not refused.
- It treated ENOENT from a directory it had itself found as proof of
  absence, so a `/proc/<pid>` exiting mid-walk ended the walk empty.

`directory_contains_protected` also answered None past its cap, and `os.walk`
silently skipped a directory it could not list.

**Remedy (small-a round 2, `d5e1a3849`, `3c6bfb394`):**

- Every glob walk is segment by segment over `os.scandir`, with no pruning.
- It counts every entry listed against a cap and checks the scan deadline
  per entry.
- It judges the root refusal on the base's real path.
- It raises on any listing error, ENOENT included. Only a LITERAL path
  component that does not exist is absence.
- `directory_contains_protected` returns `DIRECTORY_TOO_LARGE_TO_VERIFY`
  past its cap or deadline, and the guards deny on that return. It raises on
  an unlistable directory.

RED: the new `TestBoundedRecursiveGlob` cases, `TestDirectoryContainsProtected`
cases, and the quarantine ENOENT, cap, deadline and root cases. Release notes
143 and 144.

### N131 — The strict glob scan did not read a word the way the shell does

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH (S1, S2) and D-RULE (S3, S4) reviews, shared
with main.** `find_protected_mention_strict`, the quarantine guard's scan, had
several gaps:

- It expanded relative globs against the project root and the DAEMON's cwd,
  never the hook's.
- It reduced `~/` and `$HOME/` globs to relative forms.
- It matched `{a,b}` braces as literal text.
- It judged a symlink a glob reached by the link's own name.
- It walked a directory an earlier segment of the same call could have
  filled (`mkdir d && cp -r x d && cat d/*`).

**Remedy (small-a round 2, `d5e1a3849`):** the scan now judges:

- the crude tokens;
- the shell-decoded words and brace spellings of the command;
- the same again with `~`, `$HOME` and `${HOME}` replaced by the real home.

Relative globs resolve against the hook `cwd`, and a symlinked match is also
judged by its target. After a segment that is not one of a few bare
read-only heads without a redirect (`shell_segmentation.may_change_tree_or_cwd`),
a glob that could name an artefact is denied without a walk. RED: the
`TestN125GlobsAreJudgedAsTheShellExpandsThem` cases. Release note 143.

### N132 — A report claim found only in the main checkout verified a worktree agent's report

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH review (S4), shared with main.**
`subagent_report_path_verifier` looked for a relative claim under a union of
bases. The union included the event `cwd` and the project root, so a file at
the same relative path in the MAIN checkout satisfied a worktree agent's
claim, although that agent never wrote it.

**Remedy (small-a round 2, `a6bd1c821`):** when the transcript records where
the agent worked, a relative claim is looked for only in that directory and
its checkout (the nearest `.git` ancestor inside the root). A transcript
`cwd` outside the root makes a relative claim unverifiable, and it fails
closed with the absolute-path request. RED:
`test_a_claim_only_in_the_main_checkout_is_not_verified`, and the two
out-of-root cases. Release note 140.

### N134 — Guards crash on read-only commands that name no protected path

**Status on the branch**: ✅ Remedied (heredoc half: N101). **On main**: open.

**Found by the p422 D-RULE and n53 D-RULE reviews.** The live main daemon
denied read-only commands with `Internal error: TooManyToEnumerateError`:
`ls <wt>/CLAUDE/Plan/*/release-notes* ...` in `secret_file_guard`, and
`cd <wt> && ls CLAUDE/Security/; grep -rn ... CLAUDE/Security/ scripts/qa/*.yaml scripts/qa/*/*.yaml 2>/dev/null | head; find ...`
in `quarantine_artefact_read_guard`.

**Replayed on small-a round 2:** the enumeration crash is gone (N125, N130),
but the reviewer's command was still a false deny in both guards. The
leading `cd` marked every later glob unverifiable, the recursive grep's glob
roots were unverifiable, and `2>/dev/null` was read as a root.

**Remedy (small-a round 3, `2c496d4a0`, `c615ede7f`):** a leading
`cd <literal dir> &&` moves the cwd instead of marking the tree changed
(`search_pattern_arguments.split_leading_cd`; `;`, `||`, options, expansions
and a relative name under `CDPATH` are not split). A recursive grep's glob
roots are expanded by the bounded walker and each match judged. Redirections
are not roots. A cap or deadline in either guard now denies with the named
`SCAN_COULD_NOT_FINISH` reason on the ordinary rule, not the internal-error
route. RED: the reviewer shape in both guards' suites, and
`test_a_scan_that_could_not_finish_is_named_not_called_a_guard_bug`.
Release note 145.

**Duplicate half:** the `secret_file_guard` crash on an ordinary
`python3 - <<'EOF'` heredoc program is N101, fixed on `worktree-n466-n101`,
and is not fixed here.

### N136 — A dotted Python module name is read as a protected path

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by n23-land-1.** `secret_file_guard` denied
`.venv/bin/python -c "import sys; sys.path.insert(0,'src'); import claude_code_hooks_daemon.utils.secret_file_matching as s; ..."`:
the dotted module name matches the `*.secret*` default. The import exemption
only covered an import opening the `-c` argument or a line, and nothing
covered the module `python -m` runs.

**Remedy (small-a round 3, `2c496d4a0`):** every import statement inside a
quoted `-c` argument has its module path set aside, positionally, as the
opening import already did. The `-m` module of a python interpreter word is
replaced by the files Python reads for it (`a/b.py`, `a/b/__main__.py`), so
`python -m pkg.vault_pass` is still denied. A flag with a separate value
(`-X dev`), a quoted module, `-c`, and any later occurrence of the same text
are judged as written. RED: `TestADottedModuleNameIsNotAPath`. Release note
146\.

**Round 4 (M1, `84ea41968`):** every import form inside a `-c` argument
(`import a, b as c`, `from a import (b, c)`, the dynamic-import builtin and
`importlib.import_module`) is now judged as the files Python would load,
the same way `-m` is. A dynamic import whose argument is not one literal
name answers `UNRESOLVABLE_IMPORT` and is denied. Release notes 146 and 148.

### N143 — A search fed its files by another command checks no tree

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by small-a round 3.** In `find . | xargs rg x`, the guard saw an
`rg` after a pipe with no path and treated it as reading stdin data. A
non-recursive `xargs grep` or `find -exec grep` was not a search at all. So
no tree was checked, although the files searched could be any under the cwd.

**Remedy (small-a round 3b, `e4786c4f7`):** a searcher preceded in its
simple command by `xargs`, `parallel` or `find` gets the cwd tree added to
its roots. That tree is walked, never the git view, because the fed names
need not be ones `.gitignore` lets through, and a named link is opened.
Neither grep nor rg can read file names from stdin by itself, so the rest of
this class goes through those feeders. A `$( )` operand was already
unverifiable. `find` counts as tree-preserving only when it has no
`-exec`, `-execdir`, `-ok`, `-okdir`, `-delete`, `-fprint*` or `-fls`
action and no redirect. RED: `TestFilesFedByAnotherCommand`,
`test_files_fed_by_another_command_are_judged_as_the_cwd_tree`, and the
`find` rows of `TestMayChangeTheTreeOrCwd`. Release note 147.

### N144 — The quarantine guard has no Bash recursive-search check

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by small-a round 3.** `quarantine_artefact_read_guard` walked a tree
only for the Grep tool. A `grep -r x <dir holding a DETAIL artefact>` was
judged by the mention scan alone, which never sees the artefact's name.

**Remedy (small-a round 3b, `e4786c4f7`):** the N74 check moved into
`search_tree_check.recursive_search_protected_match`. Both guards call it,
so the quarantine guard judges a recursive grep/rg by the same git view or
fail-closed walk, with the same leading-`cd` and glob-root handling. RED:
`test_a_plain_rg_is_judged_by_the_git_view`,
`test_a_search_the_git_view_does_not_model_is_walked`, and
`test_a_recursive_grep_over_a_tree_holding_an_artefact_is_denied`. Release
note 147.

### N150 — Search roots and N64 report claims are resolved by text

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH re-review (BLOCKER 1, MAJOR 2).** Roots were
normalised with `normpath`, so `/root/.claude/../..` through a symlink
named a different directory from the one the search reads. The N64
verifier had the same bug.

**Remedy (small-a round 4, `0fcda9c4d`):** `resolve_search_root` resolves
each root with `realpath` after joining it to the cwd, in
`search_tree_check`, `secret_file_guard` and
`quarantine_artefact_read_guard`. `resolve_cd_target` follows bash's
logical `cd`. The N64 verifier resolves claims, cwds and the root
physically. RED: `TestASearchRootThroughASymlinkAndDotDot` in both guards
and the verifier. Release note 148.

### N151 — Git's view is trusted without checking rg reads no more than it

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH and D-RULE re-reviews (M3).** A `.ignore` or
`.rgignore` with `!build/`, a wider `core.excludesFile`, or
`RIPGREP_CONFIG_PATH` makes rg read files git's view omits, and the check
trusted that view anyway.

**Remedy (small-a round 4, `84ea41968`):** `_require_rg_reads_no_more`
verifies every precondition before git's view is used: no `.ignore` or
`.rgignore` in the tree or any ancestor, no brace in any ignore file, and
`core.excludesFile` unset or set once in the global scope. The check also
reads the daemon environment, every settings file and the command text for
`RIPGREP_CONFIG_PATH`. Otherwise the capped walk runs. RED: the brief's real
repository with `.gitignore: build/` and `.ignore: !build/`, plus a
differential `rg --files` check. Release note 148.

### N152 — A command the lexer cannot segment is read as holding no search

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH and D-RULE re-reviews (M4).** When
`recursive_searches` could not segment a command (a stray apostrophe in a
trailing comment, `grep -r x . 'open`) it returned no searches, so the
command was allowed. A searcher inside `bash -c`, `sh -c`, `eval` or a
heredoc fed to a shell was never seen, and nor was one spelled `g\rep`,
`"grep"`, `gr[e]p` or `$G`.

**Remedy (small-a round 4, `bbc950983`):** a lexer reads the command as bash
does: `#` comments, `$'…'`, `$( )`, `<( )`, `>( )`, backticks and heredocs.
Every nested command is read, bounded by
`shell_expansion.MAX_NESTED_SHELL_DEPTH`: substitution bodies, a `-c`
string, `eval`'s words and a heredoc body fed to a shell. Names are compared
after quote and backslash removal, and options are read decoded, so
`grep "-r"` is recursive. Whatever cannot be read is reported with
`unreadable=True` and denied as `COMMAND_COULD_NOT_BE_READ`. That covers an
unclosed quote or substitution, a command name behind an expansion, glob or
brace list, a wrapper running such a word, a shell reading a pipe, an
unquoted heredoc with an expansion fed to a shell, and nesting past the
bound. A word before `--` that expands may become `-r`, so it leaves the
search unclassifiable; `-e "$p"` and `-- "$f"` stay readable. `eval` of a
plain program's output (`eval "$(ssh-agent -s)"`) runs that program's
text, like a script, and stays allowed; `echo`/`printf`/here-string output
does not. `||` no longer counts as a pipe for rg's stdin case. RED:
`TestAnUnreadableCommandFailsClosed`,
`TestASearcherSpelledWithQuotesOrEscapesIsFound`,
`TestASearchInsideANestedCommandIsFound`, and the new cases in both guards.
Release note 148.

**Round 5 (`b637cdf3f`, `4a1de5936`):** a name the command assigns in any
form never takes the environment's value: it is known exactly (a
sequenced literal binding, or a `for` word list whose body holds every
reference) or unknown, and a form that does not spell the name (`read "$N"`, `printf -v "$N"`, `eval`, `source`, arithmetic reading a name)
makes every name unknown. `#` comments, `${…}` and heredoc bodies inside
`$( )` are skipped as bash skips them, and `case` there fails closed.
Parentheses end words. A `cd` moves the `&&` run after it; later commands
are judged in every directory they may run in, which also closes a bypass
in the round-4 leading-cd peel (`cd /missing && true; grep -r x .`). RED:
`untracked/scratch/n466-r5/red.txt` (all 14 shapes allowed at
`80d079be7`) and `red-paren.txt`; tests
`test_recursive_searches_bash_semantics.py` and the bash differential
`test_search_lexer_bash_differential.py`. Release note 149.

**Round 4c (`76d83cf8d`, `51fc6a143`):** a head or operand holding any
expansion was unreadable, so `P=/x/python; $P -m pytest`, `$V/ruff check f`
and `f=src/a.py; grep x "$f"` were denied. `_KnownValues` now reads each
text once per combination of the values its variables may hold: a plain-word
literal the text assigns, else the daemon's environment. A name is unknown,
and stays unreadable, when the text writes it anywhere but as a reference or
a literal binding (`read`, `for`, `let`, `+=`, `declare -n`, a quoted or
nested assignment), its assignments disagree, `IFS` is assigned, bash sets
it itself (`RANDOM`, `PWD`, `BASH_*`, ...), or a value has a blank, quote,
glob, expansion or leading `-`. The inherited value is dropped only after a
sequenced assignment (a chain of bindings from the start of the text,
joined by `;`, `&&` or newline) that precedes every reference; a nested
text always keeps it. Readings are capped at 16 per text and value chains at
depth 8; nested bodies are memoised per walk. RED on `89cd799f4`: 34 of
the new cases in `TestAVariableWhoseValueIsKnownIsRead`,
`TestAnOperandHeldInAVariable` and the secret guard. Release note 148.

### N153 — `git grep`, `ugrep`, `ag` and `ack` search a tree unchecked

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH re-review.** The recursive-search check knew
only grep and rg, so these read a protected file under the cwd without
naming it.

**Remedy (small-a round 4, `bbc950983`):** `ugrep`, `ug`, `ag`, `ack` and
`ack-grep` are treated as always recursive, with options not modelled:
every word is a root, plus the cwd, and the tree is walked following links.
The exception is one reading a pipe, with at most the pattern, which reads
only its input. `git grep` reads tracked content, so git's view judges it.
`--no-index` and `--no-exclude-standard` are walked. A pager (`-O`),
`--recurse-submodules`, pathspec magic (`:`), any global option other than
`-C`/`--no-pager`, and an expansion are unverifiable. A positional after
the pattern and before `--` may be a revision, so it must exist as a path.
RED: `TestOtherTreeSearchers`, the git grep cases in
`TestAnIgnoreHonouringSearchIsJudgedByGitsView`, and the quarantine guard's
`test_git_grep_is_judged_by_the_git_view`. Release note 148.

**Round 5 (`b637cdf3f`, `4a1de5936`):** long options resolve as git's
parse-options resolves them (exact, unique prefix, `--no-<opt>`,
`--<rest>` for `no-<rest>`); unknown or ambiguous ones and unknown letters
are unverifiable. A tree-choosing assignment (`GIT_*`, `HOME`, …), `env` or
any wrapper before `git`, or a session-wide `GIT_DIR` and kin, is
unverifiable. A pathspec is `normpath(join(realpath(base), spec))`, each
`-C` physical. A git grep is judged only through the repository git
resolves, so a `core.worktree` elsewhere is unverifiable, never walked in
its place. Release note 149.

### N154 — `run_git` passes an inherited `GIT_DIR`, `GIT_WORK_TREE` or `GIT_INDEX_FILE` through

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH and D-RULE re-reviews (shared minor).** A
caller's environment carrying one of these variables made every git probe
the guards run answer for a different repository or index.

**Remedy (small-a round 4, `0fcda9c4d`):** `run_git` removes all three after
merging in the caller's environment, so a whole-environment copy cannot
bring them back. RED: a real-repository test and a mocked one in
`test_git_repo.py`. Release note 148.

### N183 — Main's secret guard crashes on `$VAR/…` globs and brace groups

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found live in this session.** Main's daemon denied read-only commands
with `R-SECRET-EVALUATION-ERROR: TooManyToEnumerateError`: a `W=/workspace; ls $W/src/*/…` heredoc, `grep -rln … $W/tests`, and scripts whose text
named `$VAR/…` paths or `{ …; }` groups. The glob walk behind the mention
scan raised its enumeration cap, and main has no catch for that, so the
cap reached the internal-error route that calls it a guard bug.

**Remedy:** this branch's N134 path already catches it and names the deny
(or allows the command), so the fix lands with the branch. Pinned as
allow-or-named-deny over a tree past the glob cap:
`TestTheN183CrashShapesAreJudged` in `test_secret_file_guard.py`. A
quoted heredoc to a data sink, whose body names a protected key file under
the git common dir, must be a named deny. Another agent hit that shape on
main.

**Residuals (small-a round 6):** the live daemon runs with cwd `/`, and the
glob expansion used the daemon's own cwd as a base, where a two-wildcard
glob is refused outright; now only the hook cwd, else the project root, is
a base. The 2000-entry glob walk cap denied `ls */*/release*` in a large
clean tree, which main allows; it is now a budget of 100k entries or
0.2 s, past which the deny names `TooManyToEnumerateError` or
`TimeoutError`. The daemon-cwd repro is ported as
`TestTheDaemonsOwnCwdIsNoGlobBase`. Release note 150.

### N184 — A Bash read through `<link>/..` misses an absolute-path pattern

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH re-review 3 (shared minor; main has it too).**
The Bash mention scan matched a word as spelled, and resolved it only when
the word itself was a symlink. The kernel resolves `/root/.claude/../..`
links first and `..` after, so `cat <link>/../../reports/x.md` read a file
an absolute-path pattern protects, while the Read and Grep tools, which
resolve the path, denied it.

**Remedy (small-a round 5, `4a1de5936`):** a word with a `..` component is
resolved as the kernel resolves it, against the cwd when relative, before
it is matched. RED: `untracked/scratch/n466-r5/red-n184.txt` (the Bash scan
found nothing at `80d079be7`); test `TestABashReadThroughALinkAndDotDot`.
Release note 149.

### N201 — `POSIXLY_CORRECT` stops GNU grep permuting, so a word after the first operand is a file

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-RULE re-review 4 (shared; main has it too).** With
`POSIXLY_CORRECT` set, GNU grep takes every word after its first operand as
a file, options included. `export POSIXLY_CORRECT=1; grep -z x f -e P`
opens `P` (the `-z` routes the Bash tool's `grep` function to GNU grep).
The guard's option table assumed grep always permutes, so it read `P` as
the pattern and set it aside, and main's pattern-only exemption did the
same for a session that sets the variable.

**Remedy (small-a round 6):** when the command names `POSIXLY_CORRECT`, or
the session may set it (the daemon's environment or a settings `env`
block), grep's argv is also read without permutation. A word is set aside
as the pattern only when every reading agrees, and a root is any word a
recursive reading walks; main's pattern-only exemption stands down. RED:
`untracked/scratch/r6/red-archive.txt`; tests
`TestPosixlyCorrectStopsGrepPermuting`,
`test_with_posixly_correct_no_word_gnu_grep_opens_is_blanked` (real GNU
grep). Release note 150.

### N220 — A glob whose last component is a bare `*` is never expanded, so `cat dir/*` reads a protected file

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH re-review 5 (shared MAJOR; main has it
too).** `_token_mention` skipped a glob whose last component has no
literal text (`if not residue: continue`), so `cat dir/*` read a protected
file there whenever the pattern's own literal text could not be matched
against the token's. The default patterns have that shape: `cat ~/.ssh/*` read the private key. The quarantine guard's strict scan caught
the same token by expanding it; the secret guard's Bash route did not.

**Remedy (small-a round 7):** such a glob is expanded on disk like any
other, from the hook's cwd and the project root, with a leading `~/` from
the home directory. The walk is the bounded one, so past the N183 entry
or time budget it raises and the guard denies with the budget named. The
directory check expands it from every directory a `cd` may lead to as
well (`cd .. && cat vault/*`). RED: `untracked/scratch/r7/red-archive.txt`;
tests `TestAGlobWithABareStarIsExpanded` and the `bare_star*` cases of
`TestRoundSevenReviewerShapesAreDenied`. Release note 151.

### N221 — A path in an interpreter one-liner after a `cd` is judged from the hook's cwd

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the small-a D-PATH re-review 5 (shared minor; main has it too).**
With a protected pattern that names a directory, `cd CLAUDE && python3 -c 'print(open("Plan/…/r.md").read())'` was allowed on main and on the
branch. The mention scan joined the one-liner's relative path to the
hook's cwd only. The round 6 check that reads a relative word from every
directory a `cd` may lead to judged shell words, and a one-liner's path
sits inside one (`open("Plan/…")`), so it never saw it.

**Remedy (small-a round 7):** that check also judges the command text's
own path tokens, the ones the mention scan reads, from the directory a
proven `cd` leads to, or from every directory an unproven one may leave.
An unreadable `cd` target stays unverifiable. RED:
`untracked/scratch/r7/red-archive.txt`; tests
`TestAPathInAnInterpreterOneLinerAfterACd`. Release note 151.

### N249 — An interpreter one-liner's path is missed when the code is double-quoted with escaped inner quotes

**Status on the branch**: ⬜ Open. **On main**: open.

**Found by small-a round 9b ("Found, not fixed", main-proven; S-D).**
`python3 -c "print(open(\"w1-key\").read())"` is allowed on main
(`/workspace/src`) and on small-a under `**/w1-key`; the single-quoted
spelling is denied. The crude token split in
`secret_file_matching.command_tokens` drops the escaped literal, and
`_bash_interpreter_one_liner_mention` only reads shell-exec calls'
literals.

**Candidate remedy:** decode each interpreter's `-c`/`-e` string,
here-string and heredoc as bash hands it over, then run the delimiter
split again on the decoded text. Cover `python3`, `perl`, `node`, `ruby`,
`awk` (`getline <`), `$'…\'…'`, `python3 - <<< "…"` and `env python3 -c`.
Deferred from small-a by the owner's ruling; to be fixed on its own small
branch.

### N257 — A read through `/proc/self/cwd`, `/proc/<pid>` or `/dev/fd` is not judged, and main has the same bypass

**Status on the branch**: ⬜ Open. **On main**: open.

**Found by small-a round 10b (item 09, S-C; main has the same bypass).**
The per-process magic paths reach a protected file without naming it.
Every `realpath`/`stat` of one resolves it in the DAEMON's process, not
the command's. Probe on `671737c25`, anchored style, cwd `src/`:

| Command                                     | Verdict                                     |
| ------------------------------------------- | ------------------------------------------- |
| `cat /proc/self/cwd/../vault/*`             | allow (bypass)                              |
| `cat /proc/thread-self/cwd/../vault/w1.txt` | allow (bypass)                              |
| `cat /proc/self/cwd/../vault/w1.txt`        | allow (bypass)                              |
| `{ cat /dev/fd/3/*; } 3< ../vault`          | allow (bypass)                              |
| `cat /dev/fd/3/w1.txt 3< ../vault`          | allow (bypass)                              |
| `cat /proc/self/root/<abs vault>/w1.txt`    | allow (bypass)                              |
| `cat /proc/$$/cwd/../vault/*`               | deny, but only as `SECRET_EVALUATION_ERROR` |
| `grep -r needle /proc/self/cwd/..`          | deny (walk cap), by luck                    |

The `/proc/$$` deny is the guard crashing: the glob expander stat-ed
`/proc/40/cwd` in the daemon (PermissionError).

**Candidate remedy (the round 10b design):**

1. A detector in `utils/realpath.py`, `enters_process_entry(path) -> bool`.
   It walks the absolute path by hand with `os.lstat`/`os.readlink`, at
   most 40 link hops, and never `realpath`s a candidate. It is True when
   a candidate matches `^/proc/(self|thread-self|\d+)/.+` or
   `^/dev/(fd|stdin|stdout|stderr)(/|$)`, so a link in the tree
   (`p -> /proc/self`, or a relative climb to `/proc`) is caught as well
   as the literal spelling. `realpath()` itself stays unchanged, and the
   module docstring says why.
2. A textual rewrite first: a leading `/proc/self/cwd` or
   `/proc/thread-self/cwd` becomes the command's tracked cwd. After
   collapsing `//` and `/./`, `cat /proc/self/cwd/a.py` is judged as
   `./a.py` and allowed. Any other hit is a new `PROCESS_PATH_IS_UNKNOWN`
   message, returned where a pattern is, the way `FILES_MAY_HAVE_MOVED`
   is.
3. The detector runs before any `realpath`, stat or glob at these
   chokepoints: `sfm.join_against_cwd`, `resolve_search_root`,
   `resolve_cd_target`; `_realpath_if_resolvable` (its None means "no
   link", so it needs its own signal or it fails open);
   `protecting_pattern` (next to `has_symlink_loop`);
   `_protected_match_or_target`; the walk's `real_dir` in
   `directory_contains_protected`; and
   `shell_expansion.bounded_recursive_glob` (the crash site).
4. Tests: every row above with a bash differential, checking in a sandbox
   `cd` that bash's `/proc/self/cwd` is the command's cwd; plus
   `cat /proc/self/cwd/a.py` (allowed), a tree link `p -> /proc/self`, and
   `/dev/stdin` as a glob base. Accepted cost: `cat /proc/self/status` and
   `cat /proc/net/dev` (`/proc/net` links to `self/net`) become UNKNOWN.

Deferred from small-a by the owner's ruling (a branch lands once it is
strictly better than main); to be fixed on its own small branch.

## Branch `worktree-p422-close`

### N134 — Guards crash on read-only commands that name no protected path

**Status on the branch**: ⬜ Open (small-a). **On main**: open.

**Found by the p422 D-RULE review** (Plan 00422, review of
`fe14348e7..f89edf854`, report
`untracked/agent-reports/auto/260926-142224-p422-review-rule-ap422-review-rule-2c385ee357b835eb.md`).
The reviewer tried to run an in-memory probe matrix for
`orchestrator_simulate`: an ordinary Python heredoc that built hook inputs
and called the handler, and named no protected path. The live daemon's
`secret_file_guard` blocked it twice with `R-SECRET-EVALUATION-ERROR` /
`TooManyToEnumerateError`. The matrix never ran, so that review's N24
verdict rests on reading the code and the author's pin alone.

**Reproduced by the p422 fixer (round 2)** with a plain read-only listing,
on the main daemon: `ls <worktree>/CLAUDE/Plan/*/release-notes* <worktree>/release-notes* <worktree>/CHANGELOG*`
was denied the same way (`Internal error: TooManyToEnumerateError`). Three
unanchored globs, one of them across every plan folder, is enough.

**Why it matters:** a fail-closed crash is not a bypass, because nothing
protected is disclosed. It is a false denial, though, and it costs
verification: a reviewer who cannot run a probe reviews with less
evidence. The deny text routes the crash as a guard bug (the N11 internal-
error route), not as "could not verify this glob", so the agent is told
nothing it can act on. This is the same family as N101 (a quoted-heredoc
body enumerated as shell words), seen from a second command shape.

**Remedy:** being reworked on the small-a branch
(`worktree-n466-small-a`, see its report's "Handed off: N134 and N136"
section). Replay the crashing commands against small-a's round-2 glob
walk. Skip the walk where a glob's last component cannot name a protected
pattern. Where the walk still cannot finish, deny with a named "could not
verify `<glob>`" reason instead of the internal-error route. Pin the
read-only shapes with RED tests.

### N141 — The plan-folder `mkdir` guard is waved past by exemptions, quoted spaces, `CDPATH` and same-command links

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE re-review** (review of `fe14348e7..3f7fafeaf`,
report
`untracked/agent-reports/auto/260926-150902-p422-review-rule-2-ap422-review-rule-2-9253e92246b7f0a7.md`).
All four shapes are allowed on main `fe14348e7` as well as on the branch.
Cross-reference: 00422 N28, whose branch these fixes ride on.

- **SH1 (MAJOR): whole-command exemptions ran before the creation rule.**
  `plan_number_helper.matches()` returned early for an archive path, a
  `| wc` or a `git commit` message anywhere in the command. Each exists to
  spare a discovery scan, and each let a real creation beside it through:
  `mkdir -p CLAUDE/Plan/00999-x CLAUDE/Plan/Completed`,
  `mkdir … | wc -l`, `mkdir …; echo done | wc -c`, a trailing
  `# see CLAUDE/Plan/Completed/`, and `git commit -m "$(mkdir …)"`.
- **SH2 (minor): a quoted space split a path.** `mkdir -p 'x /../CLAUDE/Plan/00999-x'`
  read `/../CLAUDE/Plan/00999-x` as its own absolute word. The same fault,
  one character over, let a quoted `;` end the arguments early
  (`mkdir -p 'x;/../CLAUDE/Plan/00999-x'`, and `$(echo .; true)/…`).
- **SH3 (minor): `CDPATH` was not followed.** `CDPATH=/workspace cd CLAUDE && mkdir Plan/00999-x`
  from `src` lands in the plan dir.
- **SH4 (minor): a link made in the same command.** `ln -s CLAUDE/Plan p && mkdir p/00999-x`
  resolves through a link that does not exist when the guard reads the disk.

**Remedy (branch `worktree-p422-close`, round 3):**

- The creation rule is judged first. The `| wc` exemption also no longer
  spares a command that takes the latest entry. The commit-message exemption
  ends at a command substitution that runs, the rule `pipe_blocker` uses:
  every plan-dir mention must be gone once `strip_message_bodies` blanks
  the message values bash cannot run.
- One linear scan of the command (`_ShellStructure`) records what each
  position is (code, quoted, comment) and where every quote, substitution
  and subshell ends. The arguments of each `mkdir` are then read as the
  shell splits them, quotes and escapes included. A word the shell still
  has to expand keeps its quoting, so it is still judged by shape. A
  `mkdir` inside a string that another shell runs is split as that shell
  would split it. If a separator cuts it inside a quote of that inner
  shell, the guard denies, because it cannot know the words.
- A relative `cd` target that does not start with `.` or `..` is
  unknowable. Bash searches `CDPATH` for exactly those targets, and
  `cdable_vars` reads them as variable names. The Bash tool's shell can
  inherit either from a profile the daemon never sees, so the daemon's own
  environment settles nothing. `cd ./x` and `cd ../x` are still followed.
- A command that can make or move a link (`ln`, `cp`, `mv`, `rsync`, an
  archive tool, `mount`, a git work-tree command, or `symlink` in an
  interpreter one-liner) stops trusting the disk. Every path component is
  then judged by shape, absolute paths included.
- Proof: 61 of the new cases are RED on the round-2 handler. Six new
  hostile shapes are pinned linear in `TestMkdirJudgementStaysLinear`.
- **Round 4 replaced the private scan.** `_ShellStructure` read `$'…\'…'`
  and unquoted heredoc prose differently from bash, and `_LINK_ROUTE`
  matched English words. SH1 and SH3 are unchanged. SH2's quote-aware
  words now come from the shared `split_unquoted` and `tokenise_command`,
  alongside a raw-text reading that judges every `mkdir` whatever quote it
  sits in. SH4 now recognises only `ln` with `-s`/`--symbolic` (or a flag,
  a command word or text the tokeniser cannot read), so `cp -s`, `mv` and a
  git checkout are no longer treated as making a link, as on main. Details:
  00422 N28, round 4.

### N178 — A `mkdir` whose command word is built by expansion is never seen

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE final re-review** (review of `fe14348e7..3e0b67d6b`,
report
`untracked/agent-reports/auto/260926-154541-p422-review-rule-3-ap422-review-rule-3-5802aed4c9da603d.md`,
finding SH-a). Both main `fe14348e7` and the round-3 branch allow
`m=mkdir; $m CLAUDE/Plan/00999-x`. The plan-folder guard looked for the word
`mkdir`, and the shell builds this one from a variable, so there was nothing
to find. `m=mk; ${m}dir …`, `"$MK" …` and `$(echo mkdir) …` are the same
shape. Cross-reference: 00422 N28, whose branch this rides on.

**Remedy (branch `worktree-p422-close`, round 4):** the shared tokeniser
(`split_unquoted`, then `tokenise_command`) finds each simple command's
command word, past assignments and reserved words. When that word is an
expansion (`$…`, `${…}`, `$(…)` or a backtick), the command may be `mkdir`,
so each of its literal words is judged as a `mkdir` operand would be. A
literal new plan folder of this repository is denied. A command without the
text `mkdir` is read only when some word has a digit followed by a hyphen.
Tests: `test_a_command_word_built_by_expansion_is_a_possible_creation` (eight
shapes, all RED on the round-3 handler) and
`test_an_expanded_command_word_without_a_new_plan_folder_stays_allowed`
(`$EDITOR CLAUDE/Plan/<existing>/PLAN.md` and a dated argument stay
allowed). An expanded command word also counts as a possible `ln -s` for
every later path, because its flags cannot be read.

A folder name held in a variable (`$m CLAUDE/Plan/$N`) was left out of this
remedy; team-lead ruled that it must be denied too, which N188 does.

### N179 — The `&` or \`\\

**Status on the branch**: p422 D-RULE review 4. **On main**: open.

**Found by the p422 D-RULE review 4** (same report, finding SH-1). Main and
the round-4 branch both allow `mkdir 2>&1 CLAUDE/Plan/00999-x`, and the same
with `&>`, `&>>`, `>|`, `>&` and `<&`. Both read the `&` or `|` as a command
separator, so every word after the redirection went unjudged. A trailing
redirection was caught, because nothing followed it. Cross-reference: 00422
N28.

**Remedy (branch `worktree-p422-close`, round 5):** the `&` or `|` of a
redirection operator is not a separator. The raw-text reading's word end
excludes it, and the tokeniser's segmentation undoes a split there, so the
shared tokeniser reads `2>&1` as one word. Tests:
`test_a_redirection_does_not_end_the_words` and
`test_a_real_separator_still_ends_the_words`.

### N180 — The plan-folder guard misses an expanded command word after a wrapper, and quoting inside a folder number

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 4** (review of `fe14348e7..5d741fde4`,
report
`untracked/agent-reports/auto/260926-163947-p422-review-4-ap422-review-4-ccb6535d07675009.md`,
finding SH-2). N178's remedy read only the first command word, so main and
the round-4 branch both allow `sudo $m CLAUDE/Plan/00999-x`, and the same with
`env`, `command`, `eval` and the other wrappers. A folder name spelled with
quoting bash removes (`00999''-x`, `00999\-x`) never reached the tokeniser,
because the gate that lets a command without `mkdir` in is read on the raw
text, where no digit is followed by a hyphen. Cross-reference: 00422 N28.

**Remedy (branch `worktree-p422-close`, round 5):** the command word is found
past reserved words, assignments, redirections and every wrapper in
`bash_file_writes`' table, which now also lists `builtin` and `eval`; its
walk is shared as `command_head_index`, and `without_redirections` is public.
The gate accepts quote characters, a backslash or `$` between the digit and
the hyphen. Tests:
`test_an_expanded_command_word_after_a_wrapper_is_a_possible_creation` and
`test_an_expansion_that_is_not_the_command_word_stays_allowed`.

### N185 — The shared wrapper table lacks `setsid`, `doas` and other standard exec-wrappers

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 5** (same report, finding SH-A). Main and
the round-5 branch both allow `setsid $m CLAUDE/Plan/00999-x`, and the same
with `doas`, `flock <f>` and others, because `bash_file_writes`' wrapper
table did not list them. The table also had no idea of a wrapper's
positional arguments, so `chrt 10 cmd` could not be read.

**Remedy (branch `worktree-p422-close`, round 6):** each wrapper entry now
records, from its man page, the options that take a value and the
positional words before the command: `setsid`, `doas` (`-C`, `-u`), `chrt`
(one priority; `-T`/`-P`/`-D`), `ionice` (long forms added), `taskset` (one
mask), `stdbuf` (long forms added), `unbuffer`, `firejail`, `flock` (one
file; `-w`, `-E`), `chroot` (one new root; `--userspec`, `--groups`),
`runuser` (only with `-u`), and GNU `time` (`-f`, `-o`). A `flock FILE -c`
or a `runuser USER -c` runs a string, which N187 reads; `su` always does.
The bare-duration skip is now `timeout`'s one positional word. Tests:
`test_an_expanded_command_word_after_any_standard_wrapper_is_a_possible_creation`,
`test_a_wrapper_that_runs_no_expanded_creation_stays_allowed` and
`test_command_head_index_skips_assignments_flags_and_wrappers`.

### N186 — After an expanded command word, a folder name in `$'…'` quoting or braces is not decoded

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 5** (same report, finding SH-B). Main and
the round-5 branch both allow `$m CLAUDE/Plan/$'00999-x'`, `$"…"` and
`$m CLAUDE/Plan/0{0999,1000}-x`. The same spellings after a literal `mkdir`
are denied. `remove_word_quoting` read `$'00999-x'` as `$` then a quoted
word, which gives `$00999-x`, not a literal. The literal-word filter then
dropped it, and the gate's digit-hyphen hint missed a digit followed by `}`.

**Remedy (branch `worktree-p422-close`, round 6):** `remove_word_quoting`
decodes `$'…'` with the shared ANSI-C decoder (`shell_expansion`'s, now
public as `decode_ansi_c_body`), and `$"…"`, and removes the quoting when
the result is a plain name, so `git $'\x73tash'` is also `git stash` to
every guard that uses it. A brace word after an expanded command word is
expanded with the shared `expand_braces`. A word that cannot be decoded
(quoting left undecoded, or more spellings than the brace cap) is judged by
shape, so a plan-shaped folder in it fails closed. The gate hint accepts a
brace between the digit and the hyphen, and any `$'`. Tests:
`test_an_expanded_command_word_sees_a_decoded_folder_name`,
`test_a_decoded_name_that_is_no_plan_folder_stays_allowed` and the new
`TestRemoveWordQuoting` cases.

### N187 — An expanded command word inside a string run by `eval` or `bash -c` is not read as a command

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 5** (review of `5d741fde4..637e08e53`,
report
`untracked/agent-reports/auto/260926-182039-p422-review-5-ap422-review-5-170bf666c0b1bbdc.md`,
finding SH-C). Main and the round-5 branch both allow
`eval "$m CLAUDE/Plan/00999-x"`, `bash -c "$m …"` and
`sh -c '$0 …' mkdir`. The string is one quoted word, so the expanded
command word inside it was never a command word. `bash_file_writes` had the
matching gap for `eval "sed -i …"` and `su -c "…"`. Cross-reference: 00422
N28.

**Remedy (branch `worktree-p422-close`, round 6):** a new shared primitive,
`bash_file_writes.command_string`, gives the text a command hands a shell:
`eval` joins its operands as bash does, a shell runs its `-c` program, and
`su`, `runuser` and `flock` run their `-c`/`--command` value. `eval` is no
longer a wrapper in the table but the command whose string is read.
`bash_file_writes` analyses the string as a command, and the plan-folder
guard reads it with its own tokeniser, both bounded by their nesting depth.
Past the guard's depth (eight levels) the string is not read, so every
word in it is judged, by shape where not literal: without that, nine
nested `eval`s hid the command word again. Tests:
`test_a_string_run_as_a_command_is_read_as_one`,
`test_a_string_that_runs_no_creation_stays_allowed`,
`test_a_string_run_as_a_command_is_analysed_as_one` and
`test_command_string_is_the_text_a_shell_runs`.

### N188 — After an expanded command word, a folder name under the plan dir that the shell expands is not judged

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 5** (review of `5d741fde4..637e08e53`,
report
`untracked/agent-reports/auto/260926-182039-p422-review-5-ap422-review-5-170bf666c0b1bbdc.md`,
finding SH-D). Main and the branch both allow `$m CLAUDE/Plan/$N`. The
number is in a variable, so the text shows no plan shape. N178's remedy
judged only literal words, and the gate that lets a command without
`mkdir` in needed a digit followed by a hyphen. The review graded this as
by design. Team-lead ruled that it must be denied: the argument could be a
plan folder of any number. Cross-reference: 00422 N28.

**Remedy (branch `worktree-p422-close`, round 6b):** when the command word is
an expansion, an argument that names a path directly under the plan dir,
by any of its spellings, is judged by shape if its next segment starts with
an expansion the text cannot resolve (`$N`, `${N}`, `$(…)` or a backtick).
It is then denied. The gate also lets in a command with a `/` followed by
an expansion. The deny reason says the name is left for the shell to
expand, and to use `mkplan.bash` or spell the folder name literally. A
literal non-plan name (`<pd>/Completed`, `<pd>/README.md`) stays allowed,
and so does an expansion anywhere else (`$m out/$N`, `$m CLAUDE/$N`).
The rule is deliberately broad: `$EDITOR CLAUDE/Plan/$PLAN/PLAN.md` is
denied as well, because `$EDITOR` could be `mkdir -p`. Tests:
`test_an_expanded_folder_name_under_the_plan_dir_is_a_possible_plan` (nine
shapes, all RED on 637e08e53 and on b2639c600) and
`test_a_literal_or_elsewhere_name_after_an_expanded_command_word_stays_allowed`.

### N198 — The shared wrapper table lacks `chronic`, `coproc`, `strace`, `sg` and `env -S`

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 6** (same report, finding SH-1). Main and
the branch both allow `chronic $m …`, `coproc $m …`, `strace -f $m …`,
`sg grp '$m …'` and `env -S '$m …'`, and `bash_file_writes` missed the
same writes.

**Remedy (branch `worktree-p422-close`, round 7):** `chronic` (`-e`, `-v`),
`coproc` (with an optional NAME before a grouped command) and `strace`
(every option that takes a value, per its man page) are wrappers in the
table. `sg [-] GROUP [-c] COMMAND` and `env -S`/`--split-string` hand over
a string, which `command_string` returns: `sg`'s command, and `env`'s split
string followed by the words after it. A short-flag cluster is read as
getopt reads it (`env -iS`, `sudo -Eu root`, `strace -fo log`). Tests: the
`TestWrappers` cases in `test_bash_file_writes.py`.

### N199 — The plan-folder guard misses `<pd>//$N`, `<pd>$N`, `cd <pd> && $m $N` and command words built other ways

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 6** (same report, finding SH-2). Main and
the branch both allow `$m CLAUDE/Plan//$N`, `$m CLAUDE/Plan/./$N`,
`$m CLAUDE/Plan/{$N,}`, `$m CLAUDE/Plan$N` and `cd CLAUDE/Plan && $m $N`:
N188 matched the plan dir textually only when `/` and an expansion followed
it. Round 7 probing found more of the same class, on main too: a command
word expanded anywhere but its start (`mk$d`), a glob command word
(`/bin/mkdi?`), and `$m $'it\'s' <pd>/00999-x`, which the tokeniser could
not split. `{mkdir,<pd>/00999-x}`, denied on main, was allowed on the
branch.

**Remedy (branch `worktree-p422-close`, round 7):** a word is normalised as
text (empty and `.` components dropped, a literal `x/..` folded) and matched
on the plan dir followed by an expansion with or without a `/`, after brace
expansion. A literal `cd`/`pushd` target is followed to the commands after
`&&`, `;` or a newline (not past `||`, a pipe, or `&&` behind `!`); a
prefix assignment such as `CDPATH=…` can move where the target lands but not
what it ends in, so it is followed too. The chain is shared rather than
copied, so its cost stays linear. Any command word holding `$`, a backtick,
a glob or a brace is an expansion, and a brace command word's own
expansions are judged. `$'…'`/`$"…"` spans are handed to the tokeniser
double-quoted verbatim, so each stays one word, and only a word holding one
is judged by shape (the review 6 false positive on `"$OUT/00001-run"`). A
variable command word stays denied, and the reason gives the exact
rephrase (`vi …`, `git add …`). Tests:
`test_a_child_spelled_another_way_is_a_possible_plan`,
`test_any_command_word_the_shell_builds_is_a_possible_mkdir`,
`test_undecoded_quoting_elsewhere_leaves_other_words_alone`,
`test_a_variable_command_word_fails_closed_and_names_the_rephrase` and
three new linear-cost shapes.

### N200 — An apostrophe in a comment or heredoc body hides a later quoted git subcommand from `git_stash`/`destructive_git`

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found by the p422 D-RULE review 6** (review of `637e08e53..cc523578d`,
report
`untracked/agent-reports/auto/260926-192426-p422-review-6-ap422-review-6-a91f920f7ac2db7f.md`,
finding SH-3, with MAJOR 1 as the branch's own instance). Main and the branch
both allow `# it's` followed by `git 'stash'` or `git "reset" --hard`.
`remove_word_quoting` pairs quotes lexically, so the apostrophe in text bash
never runs pairs with the quote that opens `'stash'`, and the subcommand
stays quoted. N186's ANSI-C reading made it worse on the branch: `$'a\'` in
a comment ran past `\'`, so commands main denied were allowed. A separate
defect, on main too: `git_stash` allowed the whole command when any
recovery word appeared, so `git stash list; git stash` stashed.

**Remedy (branch `worktree-p422-close`, round 7):** a second reading,
`remove_executed_word_quoting`, knows bash's grammar: a `#` that starts a
word opens a comment, a heredoc body ends at its delimiter line and is read
on its own, and `$'…'` is decoded with bash's escapes. `word_quoting_readings`
returns it beside the lexical reading, and every caller (`git_stash`,
`destructive_git`, `plan_number_helper`) denies when any reading matches.
The lexical reading is main's, except that a `$'…'`/`$"…"` span which
decodes to a plain word, and ends where a plain quote would, is decoded; so
it never moves where a span ends and cannot hide a word main showed.
`git_stash` now judges each `git stash` invocation on its own. Tests:
`test_word_quoting_reading_callers.py` (differential against main's reading
for every caller, over a corpus of comments, heredocs and ANSI-C spans),
`TestRemoveExecutedWordQuoting` and `TestWordQuotingReadings`.

### N239 — An ANSI-C quote inside a string another shell runs (`bash -c "git \$'stash'"`) is decoded by no reading of either git guard

**Status on the branch**: ✅ Remedied. **On main**: open.

### N240 — `bash_file_writes` does not report the typescript or the `-I`/`-O`/`-B`/`-T` log files `script` writes

**Status on the branch**: ✅ Remedied. **On main**: open.

### N241 — The git guards deny a message value inside a string another shell runs, and `git_stash` denies git messages and data heredocs mentioning a stash

**Status on the branch**: ✅ Remedied. **On main**: open.

**Found live on main and by p422-fix-8f.** `destructive_git` denied a
`printf … >> notes.md` whose argument quoted a commit message and named
`git reset --hard`. Round 8f recorded two more: `bash -c 'git commit -m "document --amend"'` (`destructive_git`) and `bash -c "git stash \$'pop'"`
(`git_stash`, although `pop` is the recovery form). Each reading of the
outer command showed the nested string with the quoting that made its
message data removed, and `strip_inert_spans` never saw a message there.
`git_stash` blanked nothing at all, so `git commit -m "don't run git stash"` and a `cat <<'EOF'` body naming a stash were denied. Hunting the
class found two real commands hidden, on main too: `git commit -m 'x\' ; git reset --hard ; echo 'y'` (the message pattern read `\'` as an escape
inside single quotes) and `'$(git reset --hard)'` as a `-m` value in an
unquoted heredoc body (bash substitutes there between single quotes).

**Remedy (branch `worktree-p422-close`, round 8g):** in
`command_string_readings`, a decoded word read as a command of its own is
masked in the text around it, and in the joined command `eval` parses it
appears prepared, but only when every word closes its own quotes (an open
quote in one reaches the next once joined). `git_stash` prepares every
level with `strip_inert_spans`. `strip_message_bodies` reads a value as one
shell word, reads an attached short value, covers `gh pr|issue|release`
bodies, titles and notes, and blanks nothing in an unquoted heredoc body.
Tests: `TestGitStashProseIsNotAStash`, the N241 rows of
`TestDestructiveGitCommandStrings` (both bash-differential),
`TestAMessageIsOneShellWord`, and `TestCommandStringReadings`.

**Not changed, by design:** an `echo`/`printf` argument or a `grep`
pattern that names a guarded command is still denied. Both guards are
listed in `_DELIBERATE_TEXT_MATCHERS`, and their acceptance tests embed the
command in an `echo` (Plan 00228 Decision 2). Reversing that is a separate
decision for the coordinator.

## Branch `agent-aa0e5105724aa123b-b9ce2f39`

### N41 — The fixed chain still spends several linear seconds on a heredoc-opener-heavy command, spread widely

**Status on the branch**: ⬜ Open. **On main**: open.

**Found while remedying N38** (below), profiling the FIXED chain on the same
94 KiB never-closing `cat <<'E'` fixture. With the quadratic heredoc scan
gone, the whole chain still takes ~4-6 s wall-clock (cProfile-instrumented:
14 s), not the sub-2 s the N38 candidate remedy hoped for. Per-function
profiling at both 32 KiB and 94 KiB shows every remaining hot path scales
LINEARLY with input size — call counts and `tottime` both grow by ~2.94x for
the 2.94x size increase, not the ~8.6x a quadratic term would produce — so
this is not a second N38-shaped algorithmic defect. It is real, repeated
per-token work spread across several handlers unrelated to heredoc scanning:
`secret_file_matching._token_mention` and `path_exclusion.path_matches_globs`
(each candidate path triggers `os.path.relpath`/`abspath`/`stat` calls) and
`shlex`-based tokenisation, all paid once per one of the ~9,600 pseudo-commands
this adversarial fixture manufactures (`cat`, `<<'E'` each treated as a
candidate secret-path/token by multiple independent handlers).

**Sequenced after the B3 integration, with the shell-parser consolidation**:
`secret_file_matching` and `path_exclusion` are both being rewritten on two
other in-flight branches (464's `shell_scan`/`shell_lexer`, guard-defects'
`shell_expansion`), so touching their per-token cost now would conflict
rather than merge cleanly. N38's 15 s chain-budget pin stands as the
regression backstop until then; the consolidation is expected to tighten it
to under 2 s.

**Candidate remedy:** two independent directions, either or both. (1) Reduce
the per-token constant cost in `secret_file_matching`/`path_exclusion` —
e.g. skip `os.path.relpath`/`stat` for a token that is obviously not
path-shaped before doing filesystem-touching work. (2) Add a per-event cache
(keyed by the raw command string) for expensive, purely-functional whole-command
analyses several handlers each redo independently within the SAME chain
execution — `bash_flags.split_statements`, `secret_file_matching._tokenise`,
`shell_segmentation.strip_inert_spans` are called from 4+ distinct handlers
apiece on an identical input every time a Bash command reaches PreToolUse.
Direction (2) is architectural (a chain-scoped memoisation layer) and should
be scoped as its own plan rather than bolted onto whichever handler happens
to touch it next. RED test: the whole chain on the 94 KiB fixture (already
pinned to \<15 s by N38's fix) tightens to \<2 s once addressed.
