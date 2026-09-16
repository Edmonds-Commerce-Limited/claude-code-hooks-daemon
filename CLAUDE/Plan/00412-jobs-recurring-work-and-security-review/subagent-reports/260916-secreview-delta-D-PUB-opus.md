# Security review — `D-PUB` (DELTA)

**Check**: `D-PUB` — "New code paths that publish outward: a `gh` body, an issue,
a comment, a release note, and what they can carry out of a private tree."
**Run**: Routine 00002, run 2026-001, DELTA sweep.
**Interval**: `v3.63.0..v3.64.0` (907 files, 75,521 insertions). Reviewed as a diff.
**Reviewer**: `security-reviewer` (opus), read-only. No `gh` command was run, no
network was touched, no file was created outside this report.

**Findings**: 3 new (2 high confidence on mechanism, 1 medium on disposition).
1 prior finding re-confirmed as still open and NOT re-counted.
**Was the check answerable?** Yes, in full. The interval's publishing surface is
small and entirely readable. Nothing was blocked.

**Relation to the full sweep.** Routine 00001 run 2026-001 covered
`74b0989c..5d59f7ff` — which contains this interval — and reported five D-PUB
findings (`260915-secreview-D-PUB-opus.md`). All three below are NEW against that
report. D-PUB-D2 is a sharper, undocumented instance of something that report
explicitly set aside as a documented, deliberate residual.

---

## The interval's publishing ground

- `src/claude_code_hooks_daemon/issue_report/` (10 new modules) — the generator.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/issue_filing_gate.py` (new, 497 lines).
- `src/claude_code_hooks_daemon/utils/report_scrubbing.py` (new).
- `.claude/skills/hooks-daemon/issue-report.md` (new), `bug-report.md` (reworded),
  plus their `src/…/skills/` twins.
- `scripts/debug_info.py` (Plan 00403 Tasks 1.1/1.2/1.5).
- `.claude/skills/issue-sdlc/SKILL.md` and `CLAUDE/development/IssueSdlc.md` (new).

## What was verified as SOUND, before the findings

- **Refuse-before-write holds end to end.** `issue_report/assemble.py:89-99` ->
  `build.py:217-219` -> `daemon/cli.py:7946-7950`. A refused report leaves no file.
- **Scrub-then-digest ordering is correct.** `assemble.py:229-241`. Reversed, the
  header would vouch for a document that never existed.
- **The new gate fails CLOSED on everything it cannot read.** Unreadable body file,
  oversized body file (`issue_filing_gate.py:329-342`), `-F -` on stdin (`:364-368`),
  unresolvable install mode (`:196-209`). This is the opposite disposition from
  `sensitive_content` on the same files (the full sweep's D-PUB-3); the NEW code is
  on the right side of that asymmetry.
- **`debug_info.py` announces the degraded case.** `scripts/debug_info.py:117-148`
  emits a `> **NOT REDACTED.**` banner when `report_scrubbing` cannot be loaded, and
  a separate banner when only the secret word list is unobtainable.
- **`ReportFields` is still the whole input surface** (`assemble.py:60-79`), rendered
  from that dataclass alone (`:105-143`).

---

## Finding D-PUB-D1 — the gate's working-directory fallback reads `remote.origin.url` only, while `gh` prefers a remote named `upstream`

**Citation** — `issue_filing_gate.py:254-262`:

```python
url: str | None = None
try:
    repo = GitRepo.resolve_for(Path(cwd))
    if repo is not None:
        url = repo.read_config("remote.origin.url")
except (OSError, ValueError) as exc:  # pragma: no cover - defensive
    logger.debug("Could not resolve the repository for %s: %s", cwd, exc)
    url = None
return cls._repo_slug(url) if url else None
```

reached from `_targets_upstream` (`:264-281`) as the last of three routes, and from
`matches()` (`:295-308`) via `_filing_segments`.

**What it allows.** A checkout whose `origin` is a FORK and whose `upstream` (or any
other remote name) is this repository resolves to the fork's slug, so
`_targets_upstream` answers False, `matches()` answers False, and a hand-written
`gh issue create --title ... --body 'here is my whole config'` typed in that
directory is ALLOWED — while `gh` itself files it against the PARENT, which is the
public tracker the handler exists to protect. `gh` sorts candidate remotes by name
preference (`upstream`, then `github`, then `origin`) and honours a
`remote.<name>.gh-resolved` entry written by `gh repo set-default` above all of
them; this code consults neither. The fork-plus-`upstream`-remote layout is the
standard shape for anyone who has opened a PR against this project — precisely the
population that files issues against it.

The handler's docstring (`:24-39`) makes this route load-bearing: adding it is
described as closing a hole that "was missing", and the residual is stated as "if
git cannot answer for that directory, the answer is not ours". The residual that
actually exists is wider: git answers fine, and the answer is about the wrong remote.

**The class.** A guard that re-implements another tool's DEFAULT target resolution
and implements a proper subset of it. Membership test: *does this code predict what
an external tool will do with no explicit argument — and does it consult every input
that tool consults?* The inputs `gh` uses for the base repo are `--repo`/`-R` (read
here), `GH_REPO` (read here), `remote.<name>.gh-resolved` (NOT read here), and the
remote set ordered by preference (only `origin` read here).

**Why the test suite does not catch it.**
`tests/unit/handlers/pre_tool_use/test_issue_filing_gate.py:58-68` builds its fixture
with a single `origin` remote and nothing else. Every cwd-resolution test
(`:150-172`) is a single-remote checkout — the one layout where reading `origin` and
doing what `gh` does coincide. No fixture has two remotes; none has `gh-resolved`.
The tests are correct and complete about the case they construct, and that case
cannot fail.

**Detector hypothesis.** This is the `unenumerated spelling` class already in the
register, rotated one turn: the dangerous outcome is reachable through a *repository
state* no guard's pattern names rather than a command spelling. The Defence is an
extension of `scripts/qa/check_dangerous_invocation_corpus.py` so a corpus row may
carry a fixture checkout (remote set + `gh-resolved`) alongside its command. Rows for
day one: `origin`=upstream (expect DENY, passes today); `origin`=fork plus
`upstream`=this repo (expect DENY, currently ALLOW); fork alone with `gh-resolved`
pointing here (expect DENY, currently ALLOW); `origin`=client repo (expect ALLOW).

False positives: low, but of a specific kind — the corpus records what the daemon
decides, never what `gh` would do, so a row whose expectation was reasoned out rather
than measured pins a belief about `gh` instead of a fact. That is the limitation the
`UnenumeratedSpelling.md` page already states about itself. A code-reading rule
cannot work here: no regex can see that `remote.origin.url` is the wrong question.

**Confidence.** HIGH that the code reads only `origin` — two lines I read. HIGH on
`gh`'s remote-name preference ordering and on `gh repo set-default` writing
`gh-resolved`; both are documented `gh` behaviour, neither was executed here.
**What would settle it**: in a throwaway clone whose `origin` is a fork and whose
`upstream` is this repository, run `gh repo view --json nameWithOwner` (it prints the
base repo an issue would be filed against) and compare it with the local
`remote.origin.url` value. One command, no issue filed.

---

## Finding D-PUB-D2 — `--title` is published, is outside the digest, is outside the generator's scrub, and the sanctioned command instructs the reporter to put the summary there

**Citation** — the generator's filing command omits a title
(`issue_report/upstream.py:39-50`):

```python
return f"gh issue create --repo {UPSTREAM_REPO_DISPLAY} --body-file {shlex.quote(report_path)}"
```

while the skill that tells a reporter how to file adds one
(`.claude/skills/hooks-daemon/issue-report.md:102-105`, and its `src/.../skills/`
twin): the documented command is `gh issue create --repo <upstream> --title
"<summary>" --body-file untracked/issue-reports/<report>.md`.

The gate judges `--body-file` and nothing else (`issue_filing_gate.py:353-375`);
`body_digest` (`issue_report/provenance.py:61-71`) covers the document body and
nothing else.

**What it allows.** An issue title is published, indexed first, carried in every
notification, and is exactly as unretractable as the body. The `summary` field
carried in the BODY is scrubbed of the project root and the home prefix
(`assemble.py:232-233` -> `report_scrubbing.py:92-93`) and is refused outright on a
block-word match (`issue_report/block_words.py:69-88` includes `fields.summary`).
The SAME TEXT retyped after `--title` gets neither treatment from any code in this
interval. A summary of "issue_filing_gate denies every commit in
/home/jbloggs/acme-payroll" publishes as `<project-root>` in the body and verbatim in
the title, from one run of the sanctioned procedure.

What this is NOT: `sensitive_content` appends the whole command string as a haystack
when `_GH_BODY_PATTERN` matches (`sensitive_content.py:762-774`), so a declared
secret term or a configured public pattern in the title IS caught by that handler.
What is not caught is everything the issue-report design adds on top: the
project-root/home scrub, and the reproduction-grade refusals (absolute path,
home-relative path, Windows/UNC path, a URL to a non-`github.com` host) that
`check_reproduction` (`issue_report/reproduction.py:200-255`) applies to one field of
the document and to no part of the command line.

**Why this is not the residual the full sweep already recorded.** That report
(`260915-secreview-D-PUB-opus.md:39-53`) recorded the free-text prose fields being
scrubbed for project root and home only, and correctly declined to call it a defect:
it is stated at `assemble.py:21-25` and `BUG_REPORTING.md:127-129`, and the guidance
channels extra detail into the checked field. The title has none of that. It is not
mentioned in `assemble.py`, not in the handler docstring, not in `get_claude_md()`
(`issue_filing_gate.py:403-432`), not in `BUG_REPORTING.md`, and not in the skill
beyond the line instructing you to write one. A reporter who reads every word of the
procedure is never told that one of the two fields they are instructed to supply is
outside every check — and the instructing line, `--title "<summary>"`, points at the
field whose unscrubbed value sits in the fields JSON they just wrote.

**The class.** A published surface the verification envelope does not cover, beside
one it does. Membership test: *of everything this command sends to the remote
service, which parts did the generator produce and the gate verify?* Anything
published and unverified is in class — here `--title`, and by the same test
`--label`, `--assignee`, `--milestone`.

**Why the test suite does not catch it.** `--title x` appears on every path
(`issue_filing_gate.py:445`, `:471`, `:489`) as a one-character well-formedness
placeholder. The suite exercises the flag everywhere and asserts nothing about it —
the shape that reads to a reviewer as coverage. No test can fail because no test
makes a claim.

**Detector hypothesis.** A QA check holding the inventory of flags by which
`gh issue create` publishes author-supplied text, asserting each is either verified
by `issue_filing_gate` or listed in that handler's documented gap list with a reason.
This is the SAME artefact the full sweep's D-PUB-1 and D-PUB-3 both concluded they
needed, so three findings converge on one list — an argument for building it rather
than three separate rules. False positives: low, because the list is hand-maintained
and small; the real failure mode is staleness against a new `gh` release, which is
`F-CVE`-shaped blindness rather than noise, and is why the list must be a reviewed
file rather than one inferred from the tree.

A cheaper variant, reported AS noisy: scan every `gh issue create` template in this
repository's docs, skills and handler text and require each flag to be in the
verified set. It fires on all four acceptance-test strings, the `--web` example, the
`get_claude_md()` block and the `verbose` rule text — roughly a dozen hits, most of
them prose that is correct as written. I would not ship it in that form.

**Confidence.** HIGH on every mechanism: each is a constant or a call site I read,
and the gate's scope is one regex applied to one flag. MEDIUM on severity — a title
is short and its author is thinking about a headline, so the likely leak is a
username inside an absolute path rather than a config dump. It stays in class because
the cost asymmetry the plan is built on applies unchanged: an over-refused title
costs one rewrite, a published one cannot be withdrawn.

---

## Finding D-PUB-D3 — `gh pr create` against this tracker requires no provenance, and the handler's stated exclusion list does not mention it

**Citation** — `issue_filing_gate.py:88`:

```python
_GH_ISSUE_CREATE: Final[re.Pattern[str]] = compile_command_name_pattern("gh issue create")
```

and the docstring's exclusion at `:41-45`, which names exactly one thing left out:
"a comment is deliberately NOT covered".

**What it allows.** A `gh pr create` against this repository with
`--body-file untracked/bug-reports/bug-report-<stamp>.md` publishes a body to the
same public repository, served and indexed identically, judged by this handler not at
all. `sensitive_content` does cover `gh pr create` bodies for terms and patterns
(`sensitive_content.py:249-251`), but that is the weaker guarantee, and for a
pre-scrubbed `bug-report` bundle it is structurally vacuous for the reason the full
sweep set out in its D-PUB-5.

**The honest counter-argument, stated first.** No generator produces a PR body
either, so requiring provenance on one would make contributing impossible — the
identical reasoning that correctly excludes `comment`. If that is the project's
position, the code is not wrong. The finding is that `get_claude_md()` (`:403-432`)
and the rule's `verbose` text (`:152-178`) both enumerate what is untouched —
"Issues on YOUR repository ... `gh issue comment`, `list` and `view`" — and a PR is
in neither the covered list nor the untouched list. A reader deciding whether to
route a body through the generator gets no answer, and the default assumption from a
gate named "issue filing" is that the other filing surface on the same tracker is
handled.

**The class.** Same as D-PUB-D2's, resolving to the same artefact: a publishing
surface that is neither verified nor listed as knowingly unverified. The
discriminator between this and a code defect is a decision only the owner can make,
which is why the remedy I would propose is one sentence in the exclusion list, not a
new branch.

**Why the test suite does not catch it.** No test asserts the boundary of the
handler's subject; a handler that matches one command is tested on that command. An
absent surface appears in no test, ever — the argument `CHECKS.md:58` makes for
`F-GAP`.

**Confidence.** HIGH that `gh pr create` is unjudged by this handler (one compiled
pattern). MEDIUM that it should be a finding rather than a documentation omission — I
lean to documentation and have written it that way. LOW-MEDIUM on practical
likelihood. **What would settle the disposition**: the owner saying whether a PR body
is in this gate's subject. No measurement can answer it.

---

## Prior finding re-confirmed in this interval, and NOT counted again

The full sweep's **D-PUB-5** — the `bug-report` bundle aggregates config,
environment, hostname and a log window, and no handler stands between it and
`gh issue comment --body-file` / `gh issue edit --body-file`.

This interval touched both halves and closed neither.
`.claude/skills/hooks-daemon/bug-report.md` gained a strengthened warning ("**This
output is for the person who ran it. It is not a filing artefact.** ... it must never
be pasted into a public issue") and a "When not to use" section. Correct advice, and
still only advice. The gate that landed in the same interval covers `gh issue create`
alone. Net effect on this class: documentation improved, enforcement gap unchanged,
and the one new enforcement mechanism was scoped away from the command that would
exercise it.

Recorded here rather than as a fourth finding because the class, citation and
Detector hypothesis are already written up in the full sweep, and re-numbering it
would inflate the count.

---

## Coverage statement

| Asked of D-PUB in this interval | Answered |
| --- | --- |
| The new `issue-report` generator: what can leave a private tree | Field surface, refusal-before-write and scrub-then-digest verified sound; the prose-field residual is the full sweep's, unchanged; `--title` is `D-PUB-D2` |
| The new `issue_filing_gate`: does it engage when it should | `D-PUB-D1`; fail-closed dispositions verified sound |
| The new gate: is its subject completely stated | `D-PUB-D3` |
| New release-note / release-artefact paths | None added in the interval. `gh release create` remains outside `sensitive_content` — the full sweep's D-PUB-1, not a delta finding |
| `scripts/debug_info.py` Plan 00403 changes | Verified sound — degraded redaction is announced, not hidden |
| New autonomous publishing loops (`issue-sdlc`) | Runs only where the gate stands down by design (self-install, this public repo); its outward bodies are `gh issue comment`, which `sensitive_content` covers. No new leak path out of a PRIVATE tree, so no finding |
| `bug-report` bundle reachable by a publish command | Prior D-PUB-5, re-confirmed above, not re-counted |

Nothing in this check was unanswerable. No check outside `D-PUB` was attempted; in
particular `F-PRIV` was not attempted and cannot be answered from a diff.

## Register note

None of the three is in `CLAUDE/Security/README.md`. Per that document's rule the
register is written by the caller once a class is confirmed AND its Defence exists,
so they are reported here and nowhere else.

`D-PUB-D1` has an existing home: it is `unenumerated spelling` rotated from command
text to repository state, and its Defence is an extension of
`scripts/qa/check_dangerous_invocation_corpus.py` rather than a new Detector.
`D-PUB-D2` and `D-PUB-D3` share a single Defence with the full sweep's D-PUB-1 and
D-PUB-3 — the publishing-surface inventory those two also concluded they needed. Four
findings across two runs now want the same artefact, which is the strongest argument
available for building it before the next fix.
