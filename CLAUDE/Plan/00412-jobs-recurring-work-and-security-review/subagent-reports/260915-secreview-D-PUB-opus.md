# Security review — `D-PUB`

**Check**: `D-PUB` — "New code paths that publish outward — a `gh` body, an
issue, a comment — and what they can carry out of a private tree."
**Run**: Routine 00001, run 2026-001, FULL sweep.
**Interval**: the current tree (root `74b0989cf254b24c3c713254b2c0b52ad5d7ed96` → HEAD `5d59f7ff`), reviewed as a tree, not as a diff.
**Reviewer**: `security-reviewer` (opus), read-only. No `gh` command was run; no
file was created outside this report.

**Findings**: 5.
**Overall confidence**: high on the mechanisms (each is a regex or a branch that
can be read directly); mixed on severity, stated per finding.

---

## What was verified as SOUND, before the findings

The brief asked three things to be checked rather than assumed. Two hold.

**The `issue-report` field collection does what `BUG_REPORTING.md:99-104`
promises.** `ReportFields` (`src/claude_code_hooks_daemon/issue_report/assemble.py:60-79`)
is the entire input surface and has no `hostname`, no `git_remote`, no config
field, no log field and no transcript field. `cmd_issue_report`
(`src/claude_code_hooks_daemon/daemon/cli.py:7909-7934`) populates it with the
version, install mode, a `platform_text` built at `:7921-7923` from
`platform.system()/machine()/python_version()` only, a date, the release notes
range, `home`, `project_root` and the block-word list. `:7919-7920` carries an
explicit comment that the hostname is omitted by design. Nothing downstream can
reintroduce a field, because `_sections()` (`assemble.py:105-143`) renders from
that dataclass alone. The claim "never collected rather than scrubbed" is
accurate as written.

**The refusal-before-write property holds.** `AssembledReport`
(`assemble.py:89-99`) carries an empty `document` whenever `problems` is
non-empty, `build_report` (`build.py:217-219`) returns that same empty-document
form, and `cmd_issue_report:7936-7940` returns 1 without writing. A refused
report genuinely leaves no file.

**One stated residual, reported as a residual and not as a finding.**
`assemble_report:232-233` calls `scrub_report` with `project_root` and `home`
only. `scrub_report` (`utils/report_scrubbing.py:61-95`) also accepts
`hostname=` and `git_remote=`, and the publication path supplies neither —
correctly, since neither is collected. The consequence is that the "backstop"
over the free-text `summary`/`expected`/`observed` fields removes only the
project-root and home prefixes. An internal hostname, an internal tracker URL or
a Windows path typed into `observed` is published verbatim; the equivalent
tokens typed into `reproduction` are refused by `check_reproduction`
(`issue_report/reproduction.py:200-255`). That asymmetry is deliberate and
documented at `assemble.py:21-25` and `BUG_REPORTING.md:127-129` ("It cannot
prove the prose YOU wrote inside it is safe to publish"), so it is not a defect.
It is worth recording because `BUG_REPORTING.md:131-132` actively channels
"extra detail" into `reproduction` — the checked field — which means the
guidance and the check agree, and the residual is narrower than it first looks.

---

## Finding D-PUB-1 — `gh release create` is entirely outside the publication scan surface

**Citation** — `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:249-251`:

```python
_GH_BODY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s;&|(])gh\s+(?:issue|pr)\s+(?:comment|create|edit)\b"
)
```

**What it allows.** `gh release create v3.65.0 --notes-file RELEASES/v3.65.0.md`
publishes the full content of a repository file as a GitHub release body. Neither
the inline `--notes` value nor the `--notes-file` content is scanned for a public
pattern or a secret term, because the command never matches `_GH_BODY_PATTERN`
and so never reaches `_bash_haystacks`' `gh` arm (`:762`, `:769-770`). This is
not hypothetical shape-fitting: it is verbatim this project's own release
procedure at `.claude/skills/release/invoke.sh:310-313`. A release body is as
public as an issue and, like an issue, is served, notified and indexed before any
later edit.

**The class.** A `gh` subcommand that causes GitHub to STORE author-supplied text
visible to anyone who can read the repository, and which is absent from the
publication allowlist. The membership test a reader can apply without asking:
*does this subcommand persist text I wrote to GitHub's servers?* `release create`, `release edit`, `gist create`, `pr review --body` all answer yes and all
are absent. `issue view`, `pr checkout`, `release view` answer no and are
correctly out.

**Why the test suite does not catch it.**
`tests/unit/handlers/pre_tool_use/test_sensitive_content.py:1168-1174`
parameterises exactly the eight `gh issue|pr` shapes the regex already matches,
and `:1222-1226` parameterises the read-only shapes it correctly ignores. Both
are closed-set assertions over the members the pattern was written for. No test
asserts that the set is COMPLETE, and no such test is possible without an
external list of what `gh` can publish — so the suite cannot fail on an
under-enumerated surface, however far under it is.

**A reader of the docs is actively misled here**, which raises this above a bare
omission: `get_claude_md()` at `sensitive_content.py:1231-1237` enumerates the
covered subcommands and then names the gaps — "`gh api` is not covered… a body
piped on stdin (`-F -`) cannot be judged". A reader reasonably concludes those
two are the gaps. `release` is not mentioned in either list.

**Detector hypothesis.** A QA check holding a maintained list of `gh`
subcommands that publish a body, asserting each appears in `_GH_BODY_PATTERN`'s
alternation OR in the handler's documented gap list — so adding a subcommand to
the gap list is a deliberate, reviewable act rather than an omission. Likely
false positives: low, because the list is hand-maintained and small; the real
failure mode is the list going stale against a new `gh` release, which is an
`F-CVE`-shaped blindness rather than noise.

A cheaper noisy variant, worth reporting AS noisy: grep the repository for
`gh\s+\w+\s+\w+.*--(notes|body)(-file)?` and require each matched subcommand pair
be covered. This fires on every documentation example, every acceptance-test
string and every `get_claude_md()` block in the tree — in this repository that is
dozens of hits, most of them prose. I would not ship it in that form.

**Confidence.** HIGH that the gap exists; the regex is explicit and I read it.
HIGH severity for this repository, which cuts releases with exactly this command.
MEDIUM-LOW for a client install, which rarely publishes releases through daemon
tooling — but the guard is client-facing, so the low number is about likelihood,
not about whether it should be closed.

---

## Finding D-PUB-2 — a git message named by file or by command substitution is published unscanned, while a sibling handler already reads exactly those files

**Citation** — `sensitive_content.py:762-774`. The git-metadata arm appends only
the command text:

```python
if self._writes_git_metadata(command) or _GH_BODY_PATTERN.search(command):
    haystacks.append(_Haystack(subject=command, text=command))
if _GH_BODY_PATTERN.search(command):
    haystacks.extend(self._gh_body_file_haystacks(command, hook_input))
```

The file-reading branch is gated on `_GH_BODY_PATTERN`, so it never runs for a
`git` command. Contrast
`src/claude_code_hooks_daemon/handlers/pre_tool_use/github_auto_close_keywords.py:130-132`,
which covers the same commands and does read the file:

```python
_MESSAGE_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:-F|--file|--body-file)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)
```

with the read at `github_auto_close_keywords.py:253-257` and the behaviour stated
in its own docstring at `:30-31`.

**What it allows.** Two concrete shapes, both in this project's own procedures:

- `git tag -a v3.65.0 -m "$(cat RELEASES/v3.65.0.md)"` —
  `.claude/skills/release/invoke.sh:307`. `_writes_git_metadata` matches (`tag`
  is in `_GIT_METADATA_WRITE_SUBCOMMANDS:121-129`, no read-only flag is present),
  so the handler DOES engage — and then scans the 26-character literal
  `$(cat RELEASES/v3.65.0.md)`. Bash expands it after the hook has allowed the
  command. The whole file becomes an annotated tag message, which `git push origin vX.Y.Z` puts on a public remote, where it cannot be rewritten once
  anyone has fetched it.
- `git commit -F untracked/msg.txt` — the message file is not a staged blob, so
  the staged-content arm (`:829-852`) does not reach it either. The commit
  message is recorded unscanned.

The handler engaging and finding nothing is worse than not engaging: the log and
the verdict both record that the guard ran.

**The class.** A command whose PUBLISHED payload is named by reference — a file
path, a command substitution — where the guard scans the reference instead of the
referent. Membership test: *does the text git or GitHub will store differ from
the text on the command line?* If yes, scanning the command line is scanning the
wrong string.

**Why the test suite does not catch it.** Every git-metadata test supplies the
term inline. The handler's own acceptance test at `sensitive_content.py:1351`
is `git commit -m "<term>"`; the `--body-file`/`-F` tests at
`test_sensitive_content.py:1186-1213` are all `gh`. `--file` does appear in this
handler, at `:159-174` in `_COMMIT_LONG_FLAGS_WITH_VALUE` — but purely as a token
to SKIP while detecting `-a`, which is the trap: the flag is present in the
source, so a reader scanning for it concludes it is handled.

**Detector hypothesis.** Assert that `sensitive_content`'s body-file regex is a
superset of `github_auto_close_keywords`' message-file regex — two handlers
judging the same commands must not disagree about which flags carry content, and
the one whose subject is leak prevention must not be the narrower. Concretely: a
QA check importing both patterns and comparing their flag alternations. False
positives: essentially none; the check is an equality assertion between two
constants in this repository's own source. It will need updating when either
handler legitimately diverges, and that is the point — the divergence becomes a
decision.

The general form (every file-valued flag is either read or listed as unread with
a reason) is the one that finds the whole class, and is noisier: it fires on
read-only handlers such as `gh_issue_comments` that legitimately never read a
file, so it needs an opt-out that would itself need policing.

**Confidence.** HIGH. The mechanism is directly readable, the sibling handler
proves the technique is available and already implemented in this codebase, and
the exploiting command is in the project's own release script rather than
invented for the report.

---

## Finding D-PUB-3 — an unreadable or oversized `gh` body file fails OPEN on the one surface that cannot be retracted, while the gate on the same file fails CLOSED

**Citation** — `sensitive_content.py:819-827`:

```python
try:
    if path.stat().st_size > _MAX_BODY_FILE_BYTES:
        _LOGGER.info("sensitive_content: gh body file %s exceeds the size bound", path)
        return ""
    raw = path.read_bytes()
except OSError as error:
    _LOGGER.debug("sensitive_content: gh body file %s could not be read: %s", path, error)
    return ""
```

`:797-798` then drops the file from the haystack list, and with no other match the
command is ALLOWED. Compare `issue_filing_gate.py:329-342`, which applies the
identical 65,536-byte bound to the identical class of file and returns
`(None, reason)`, which `:370-372` turns into a refusal. Its docstring at
`:322-327` states the principle this handler does not follow: *"An unreadable body
file is a REFUSAL rather than a pass. The whole point of the gate is that nothing
unchecked is filed, and 'I could not read it' is not a check."*

**What it allows.** `gh issue comment 12 --body-file notes.md` where `notes.md` is
70 KB posts the comment with no content scan at all. The bound matters more than
it looks: `_MAX_BODY_FILE_BYTES` is 65,536 BYTES while GitHub's own comment limit
is 65,536 CHARACTERS, so a body of roughly forty thousand multibyte characters is
comfortably inside what GitHub accepts and outside what this handler will read.
The same branch covers a file whose mode denies read, and a file unlinked between
the `path_is_file` stat at `:793` and the read at `:823`.

**The same asymmetry appears on stdin, and it is worth naming separately.** For
`-F -`, `issue_filing_gate.py:364-368` REFUSES ("the body is being piped in on
stdin, which cannot be read before the fact"); `sensitive_content.py:785-786`
`continue`s. Same token, same impossibility of judging it, opposite verdicts. The
practical consequence is that the upstream `gh issue create` stdin route is
closed while the `gh issue comment`/`gh issue edit` stdin route is open — so the
gap the project documents as "a body piped on stdin cannot be judged" is
accurate about the cause and understates which surfaces it leaves open.

**The class.** A guard whose "I could not judge this" branch resolves to ALLOW on
an action that cannot be undone. Membership test: *if the check cannot run, does
the guarded outcome still happen, and can it be retracted afterwards?*

**Why the test suite does not catch it.** This is the strongest case in the set,
because the tests are the reason nobody looks:
`test_sensitive_content.py:1239` is `test_missing_body_file_is_allowed`,
`:1246` is `test_stdin_body_file_is_allowed`, `:1252` is
`test_a_body_file_that_cannot_be_read_is_skipped_and_logged`. The fail-open is
written down as the specification and asserted. The suite passes, will keep
passing, and reads to a reviewer as deliberate coverage of the branch.

**The honest counter-argument, stated because it is half right.** For a MISSING
file, allowing is correct — `gh` fails on its own and nothing is published, which
is exactly the reasoning at `:780-782`. For an OVERSIZED file, and for a present
file the process cannot read, `gh` SUCCEEDS and publishes. The defect is that one
branch serves both cases: the comment justifies the behaviour using the missing-
file case and applies it to the publishing cases. Splitting them is a small
change and needs no new bound.

**Detector hypothesis.** Flag, in handlers carrying `HandlerTag.SAFETY` and
`HandlerTag.TERMINAL`, any `except OSError` or size-bound branch whose value
feeds a haystack/candidate collection rather than a deny. I expect this to be
NOISY and report it as such: the staged-diff stand-down at `:873-875` and the
per-file bound at `:886-891` are the same shape and are arguably correct, because
a commit can be amended before it is pushed while a comment cannot be recalled.
The discriminator — *is the guarded action retractable?* — is a property of the
surface, not of the code shape, so no regex can see it. The honest form is a
hand-maintained list of irreversible surfaces (`gh` publish subcommands, the
`Artifact` tool) with the rule applied only to branches reachable from them; that
list is small and is the same artefact D-PUB-1's detector needs, so the two
should share it.

**Confidence.** HIGH on the behaviour (it is asserted by name in the tests).
HIGH that the oversized case is a defect. MEDIUM on whether the project will
agree the missing-file case should change — I think it should not, and have said
so above.

---

## Finding D-PUB-4 — the `gh` publication anchor is not hardened against a path-qualified binary, in a handler that hardens `git` against exactly that, forty lines away

**Citation** — `sensitive_content.py:249-251` anchors on a bare name:
`(?:^|[\s;&|(])gh\s+`. The same file, at `:995`, hardens `git`:

```python
if token != _GIT_EXECUTABLE and not token.endswith(f"/{_GIT_EXECUTABLE}"):
    continue
```

And `utils/command_evasion.py:98` provides the fragment written for precisely
this — `OPTIONAL_PATH = r"(?:\S*/)?"` — which `issue_filing_gate.py:88` consumes
via `compile_command_name_pattern` (`command_evasion.py:197-198`) and
`sensitive_content` does not.

**What it allows.** `/usr/bin/gh issue comment 12 --body "<term>"` and
`./gh issue create …` do not match, so neither the inline body nor any
`--body-file` is scanned. The `git` half of the same handler would catch the
equivalent `/usr/bin/git commit`.

**The class.** A bare-name command anchor in a blocking handler — verbatim the
class `command_evasion.py:1-27` exists to close, whose docstring names three
handlers this already defeated (`destructive_git`, `sudo_pip`,
`curl_pipe_shell`) and concludes: *"All three are one defect: a bare-name
anchor."*

**Why the test suite does not catch it.** Every `gh` test in
`test_sensitive_content.py:1168-1288` writes a bare `gh`. There is no test
asserting that command-anchored handlers consume the shared fragment, and the
handler's `git` arm passing its own path test at `:995` gives the file the
appearance of being hardened.

**Detector hypothesis.** A QA check flagging any `re.compile` under `handlers/`
whose pattern embeds a literal command name immediately followed by `\s` without
`OPTIONAL_PATH` or `ENV_PREFIX` preceding it. Likely false positives: patterns
that match a command name inside PROSE — `get_claude_md()` bodies, advisory text
and acceptance-test strings all contain command names in this codebase — plus the
occasional pattern that deliberately matches only the bare name. The population
of compiled patterns in `handlers/` is small and enumerable, so a first run is
reviewable by hand; I would expect a handful of legitimate exemptions.

**Confidence.** HIGH on the mechanism — it is two constants in one file
disagreeing. LOW-MEDIUM on practical exploitability: nobody types `/usr/bin/gh`
by accident, so this is an evasion gap rather than an accident gap, and this
project explicitly designs its guards for the accident (`issue_filing_gate.py:47-51`
says so). It remains in class because the shared fragment exists, is used by the
neighbouring handler, and closing the gap costs one regex edit.

---

## Finding D-PUB-5 — `bug-report` assembles the exact bundle the SOP forbids publishing, and nothing stands between it and `gh issue comment --body-file`

**Citation** — `daemon/cli.py:7692-7697` inlines the complete config file:

````python
if config_path.exists():
    config_content = config_path.read_text()
    sections.append(f"**Path:** `{config_path}`\n")
    sections.append("```yaml")
    sections.append(config_content.rstrip())
````

plus `:7736-7774` (a 100-line log window, `_BUG_REPORT_LOG_LINES = 100` at
`:7583`), `:7776-7782` (environment variables including `HOSTNAME` and
`VIRTUAL_ENV`, listed at `:7585-7593`) and `:7651` (the hostname). Every one of
those four is in `BUG_REPORTING.md:19-24`'s "Never file" table.

**What it allows.** `gh issue comment <n> --repo Edmonds-Commerce-Limited/claude-code-hooks-daemon --body-file untracked/bug-reports/bug-report-<stamp>.md`
posts a client's whole daemon config, environment and log window to a public
tracker. No handler judges it:

- `issue_filing_gate` matches only `gh issue create`
  (`issue_filing_gate.py:88`) and stands down for comments deliberately
  (`:41-45`).
- `gh issue edit <n> --body-file <same file>` is outside the create-gate for the
  same reason — and an edit REPLACES a body the gate previously verified, which
  is a strictly worse outcome than a comment.

**The reasoning that licenses the stand-down is inverted for this file
specifically, and that is the finding.** `issue_filing_gate.py:44-45` justifies
leaving comments alone: *"The secret-term scan in `sensitive_content` already
covers `gh issue comment` bodies, which is the leak class that cannot be
retracted."* But `_scrub_bug_report` (`cli.py:7984-7991`) has already run
`scrub_report(..., secret_terms=get_active_secret_terms())` over that document,
replacing every declared term with a placeholder. So `sensitive_content`'s
secret-term arm is STRUCTURALLY GUARANTEED to find nothing in a bug report. The
public-pattern arm is weakened the same way, because the same call has already
replaced the project root and the home prefix — the two things a client's public
patterns are most likely to describe.

The document most dangerous to publish is the one document the compensating
control is certain to pass. The only thing standing against it is a sentence:
`.claude/skills/hooks-daemon/SKILL.md:295` — *"LOCAL diagnostic bundle — for you
to read, never to publish"*.

**The class.** A locally-generated diagnostic that deliberately aggregates
material the project forbids publishing, whose only protection is documentation,
reachable by a publish command no handler judges. Membership test: *does a
generator in this repository produce a file that its own docs say must not be
published — and can a `gh` publish command name that file?*

**Why the test suite does not catch it.** The two halves live in different
modules with separate suites, and each suite is correct on its own terms.
`test_issue_filing_gate.py` asserts the comment stand-down (which is right, given
its premise); `test_sensitive_content.py` asserts the term scan fires on a
comment body (which it does, on a body that has not been pre-scrubbed). Neither
suite can express "the scrubber ran first, so the scan is vacuous", because that
is a property of the INTERACTION between the CLI's scrub step and the handler's
scan step. This is the `D-PUB` face of `F-BYPS`, and it is the case
`CHECKS.md:57` describes: *"A bypass is created by the INTERACTION of files, and
both can be unchanged."*

**Detector hypothesis.** Give `bug-report` output a generator-written marker —
an anti-provenance header, the inverse of `issue_report/provenance.py`'s — and
have a handler deny any `gh` publish command whose `--body-file`/`-F` names a
file carrying it. False positives: near zero, because the marker is written by
the generator rather than inferred, and only that generator writes it. The cost
is one new line in the bug-report format and one handler branch, and it reuses
machinery this repository already has.

A cheaper variant, reported as slightly noisier: deny any `gh … --body-file`
whose resolved path is under `untracked/bug-reports/`. This is a path rule rather
than a content rule, so it false-positives only if someone moves a legitimate
generated issue report into that directory — unlikely, but it is a rule about
where a file sits rather than what it is, which is the weaker of the two.

**Confidence.** HIGH on the mechanism and on the vacuousness argument; both are
readable in the two cited call sites. MEDIUM-HIGH overall, with the limit stated
plainly: I enumerated the handler set by grepping `handlers/` for `gh`-matching
patterns rather than reading every handler, and I ran no `gh` command (the brief
is read-only). A handler I did not open could in principle cover this path. What
would settle it: dispatch the command shape through the daemon's own acceptance
harness against a throwaway repository, or run `bin/hooks-daemon explain-handler`
across the `GITHUB`-tagged set and confirm none claims the comment surface.

---

## Coverage statement

Every item the brief named was looked at, and each produced an answer rather than
a gap in the review:

| Asked                                                                                   | Answered                                                                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `issue-report` field collection                                                         | Verified sound — see the section above `D-PUB-1`                                                                                                                                                                                                       |
| Bug-report / diagnostic bundle, and whether anything can publish one                    | `D-PUB-5`                                                                                                                                                                                                                                              |
| `sensitive_content` coverage of `gh issue/pr create\|edit\|comment` incl. `--body-file` | Covered as documented; the gaps are `D-PUB-1`, `D-PUB-3`, `D-PUB-4`                                                                                                                                                                                    |
| Anything building a commit message, tag message or branch name from file content        | `D-PUB-2`                                                                                                                                                                                                                                              |
| The stated `gh api` and stdin gaps — what they actually permit                          | `gh api` is genuinely uncovered by both `sensitive_content` and `issue_filing_gate`, as documented, and I found nothing in this tree that invokes it to publish. The stdin gap is NOT symmetric between the two handlers — see the middle of `D-PUB-3` |

Nothing was unanswerable. No check outside `D-PUB` was attempted.

## Register note

None of the five is recorded in `CLAUDE/Security/README.md`, whose only category
is `authored path resolution`. Per that document's own rule, the register is
written by the caller once a class is confirmed AND its Defence exists — so these
are reported here and nowhere else. `D-PUB-2` and `D-PUB-4` are the two whose
Defence is cheap enough to land in the same session as the fix, which is the
order Defence Before Fix requires.
