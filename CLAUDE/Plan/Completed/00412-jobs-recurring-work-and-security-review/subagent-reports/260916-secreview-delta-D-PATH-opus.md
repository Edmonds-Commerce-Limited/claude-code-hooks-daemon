# Routine 00002 delta run 2026-001 — check `D-PATH`

**Check**: `D-PATH` — new filesystem writes, and whether each is inside project
containment; new path handling that a `..` or a symlink could walk out of.

**Interval**: `v3.63.0..v3.64.0` (432 commits, 907 files; 266 under `src/`,
`scripts/`, `bin/`).

**Answerable**: yes. The diff was produced and read. Nothing was skipped for
want of a tool or an unreadable path. Candidates examined and found sound are
listed under "Examined and clean" rather than omitted — a silent omission and a
clean result are not the same answer.

**Findings**: 2 confirmed, 2 secondary observations.

---

## Finding 1 — the markdown-location guard's new existence test stats the wrong file inside a worktree

**Citation**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py:1049`
and `:1084-1087`.

```python
        if path_is_file(self._candidate_on_disk(file_path), unreadable_means=False):
            return False
...
    def _candidate_on_disk(self, file_path: str) -> Path:
        """The on-disk path a Write/Edit names: absolute as given, else under the workspace."""
        candidate = Path(file_path)
        return candidate if candidate.is_absolute() else self._workspace_root / candidate
```

`self._workspace_root` is bound once, at handler construction, to
`ProjectContext.project_root()` (`:234`) — the MAIN project root.

**The path the stat asks about is not the path being written.** By the time
line 1049 runs, `file_path` may have been rebound at `:1016-1018`:

```python
            effective_relative = effective_project_relative_path(file_path, project_root)
            if effective_relative is not None:
                file_path = effective_relative
```

`effective_project_relative_path` (`core/worktree_paths.py:49-74`) returns a
path relative to the **worktree** root for anything under
`.claude/worktrees/<name>/` or `untracked/worktrees/<name>/`, discarding the
worktree segment. `_candidate_on_disk` then rejoins that remainder onto the
**main** project root, so the predicate stats the same-named file in the main
checkout.

**What it allows**, both directions:

- *False exemption.* A Write to
  `<root>/.claude/worktrees/agent-X/stray/notes.md` is re-rooted to
  `stray/notes.md` and the stat lands on `<root>/stray/notes.md`. If the main
  checkout happens to carry that relative path, the worktree write is exempted
  from the location rule although nothing exists at the worktree path. The
  guard is silent on a genuinely new misplaced file.
- *False block — the one the change was written to remove.* An `Edit` of a
  `.md` that really does exist at a non-allowed location inside a worktree is
  stat-ed in the main checkout, found absent, and denied. Worktrees are this
  project's standard concurrent-agent workflow, so this is the everyday path.

`Path.is_file()` also follows symlinks, so a symlink at the resolved location
pointing at any existing file exempts the write too.

**The class**: *a stat whose joined base is not the base the value is relative
to.* The value and the root come from different coordinate systems — one
re-rooted to a worktree, the other fixed at construction — and the join
silently produces a real, wrong path. Mechanically: if a function re-roots a
path for CLASSIFICATION and a later statement re-joins it for a FILESYSTEM
operation, the site is in the class. This is the register's
[authored path resolution](../../../Security/AuthoredPathResolution.md) class
generalised one step: that class is about `..` walked through the filesystem,
this is about the *base* being wrong rather than the *remainder*. Both are "the
predicate answered a question about the route, not about the target".

**Why the test suite does not catch it**: the two relevant test sets vary
disjoint variables and neither varies both.

- `tests/unit/handlers/pre_tool_use/test_markdown_organization.py:2645-2668`
  (the new existence tests) use a **relative** `file_path` (`"stray/notes.md"`)
  with `handler._workspace_root = tmp_path` (`:2568-2572`). A relative path
  never enters the `is_absolute()` branch at `:999`, so the worktree re-rooting
  is never reached.
- `:726-758` (the worktree tests) use absolute paths under `/tmp/test/...`
  that **do not exist on disk**, so `path_is_file` returns `False` and the
  location is judged exactly as before. Those tests still pass with the defect
  present.

This is the third instance of the lesson the register already records: not a
missing test, a missing *variable*. The fixture embodies the assumption the
defect violates.

**Detector hypothesis**: flag a stat/read predicate applied to a path joined
onto a root captured in `__init__` (or at module scope) when, anywhere on the
control-flow path to that call, the joined name was reassigned from a
re-rooting helper — concretely, any function in `handlers/` that both calls
`effective_project_relative_path` (or rebinds a `file_path` parameter) and
later reaches `path_is_file`/`path_exists`/`path_is_dir`/`read_text`. A
narrower and cheaper variant with the same catch: **any** use of
`self._workspace_root / <name>` in a function that also calls
`effective_project_relative_path`.

*Likely false positives*: a handler that re-roots for classification and joins
onto a root for a genuinely main-repo-scoped lookup — reading
`.claude/settings.json` at `markdown_organization.py:670` is exactly that and
would fire. I estimate a handful of sites, so this is reportable as a low-noise
rule; but it is a rule about a *pair* of statements, so it inherits the "one
statement, not two" difficulty that already cost the existing Defence a
widening.

**Why the existing Defence does not catch it**, on two independent counts —
both blind spots the register already names in `AuthoredPathResolution.md`:

1. *"Only two trees."* `scripts/qa/check_authored_path_stat.py:91` scopes to
   `_SCOPED_TREES = ("docs_qa", "plan_qa")`. `handlers/` is not scanned. The
   register's own words: *"A third tree that starts resolving authored paths
   must be added to `_SCOPED_TREES`; nothing will notice on its own. That is
   the live risk in this design."* **That blind spot now has a live member.**
2. *"One statement, not two."* Even inside a scoped tree the rule would miss
   it: the receiver is a function CALL result
   (`path_is_file(self._candidate_on_disk(file_path))`), and the join lives
   inside that function. The register: *"A value that travels through a second
   assignment, a container, or a function boundary is invisible."*

**Confidence**: high that the code path is as described — the re-rooting, the
construction-time root and the rejoin were each read directly. Medium on how
often the false-exemption direction bites in practice: it needs a same-named
relative path to exist in the main checkout. The false-block direction needs
only a worktree, so I rate that near-certain to occur.

**What would settle it**: one test that writes to a path inside a
`.claude/worktrees/<name>/` subtree where the file exists at the worktree path
and not at the main-root path, asserting `matches()` is `False`.

---

## Finding 2 — a new daemon subcommand writes to any path the caller names, and `project_containment` cannot see it

**Citation**: `src/claude_code_hooks_daemon/daemon/cli.py:7962-7966`
(`cmd_issue_report`).

```python
    else:
        output_path = Path(output_target)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(report.document)
```

`output_target` is the `--output` flag, unvalidated: absolute, `..`-relative
and symlinked destinations are all written, and missing parents are created.

**What it allows**: `bin/hooks-daemon issue-report … --output /tmp/x/report.md`
creates a directory tree and writes a file outside the repository, and
`project_containment` returns ALLOW. That handler enumerates the command shapes
it understands — redirects/`tee`/heredoc, `cp`/`mv`/`install`/`dd`, `curl -o`,
`wget -O`, `tar -cf`, `mkdir`, `rsync`/`scp`, nested `sh -c`
(`project_containment.py:111-134`, `_destination_targets`) — and `hooks-daemon`
is not among them. The handler's own `get_claude_md` calls that list
**"exhaustive, not illustrative — and one gap remains"**, naming only the
interpreter one-liner. This is a second gap, and unlike the first it is one the
daemon ships itself.

**The class**: *a first-party command that takes a destination path and is not
in the containment guard's command table.* Membership is mechanical: any
argparse argument used as a write destination, on any command the guard does
not key on.

**New in the interval?** The *shape* is not — `bug-report --output`
(`cli.py:7832`), `generate-docs --output` (`:2902`) and `regenerate-docs` all
pre-date `v3.63.0`, verified by reading the `v3.63.0` copy of `cli.py` at lines
6345-6362. `issue-report --output` is the **new instance**, added with the
whole `issue_report/` package in this interval. Reported as an instance of an
unregistered class, not as a new class.

**Why the test suite does not catch it**: `project_containment`'s tests assert
the shapes it *does* recognise. A command the extractor yields nothing for
produces no target, no match and no handler invocation — indistinguishable in a
test from a command correctly judged safe. There is no test asserting "every
first-party command with a destination flag is in the table", because nothing
enumerates that set.

**Detector hypothesis**: parse `cli.py`'s argparse tree for arguments whose
value reaches a `write_text`/`open(…, "w")`/`mkdir` (or, cheaply and with more
noise, whose `dest` is in `{output, out, output_dir, dest, file}`), and assert
each owning subcommand is either keyed in
`project_containment._OUTPUT_FLAG_COMMANDS` or explicitly listed as exempt.

*Likely false positives*: `--output -` (the stdout sentinel, which
`issue-report` and `bug-report` both honour) and flags whose default already
resolves under `untracked/`. Both are cheap to whitelist. The fix is one dict
entry — `_OUTPUT_FLAG_COMMANDS["hooks-daemon"] = frozenset({"--output"})` —
because the table is keyed on `Path(tokens[0]).name`, so `bin/hooks-daemon`
matches.

**Severity**: low-moderate. The operator or agent *names* the path, so nothing
is smuggled; what is lost is the durability guarantee the guard exists to
enforce, and the guard's claim to an exhaustive list.

**Confidence**: high. Both the write site and the containment table were read
directly; the CLI flag registration was confirmed at the parser.

---

## Secondary observation A — the issue-filing gate reads any path the command names

**Citation**: `handlers/pre_tool_use/issue_filing_gate.py:313-342` (new file).

```python
    def _resolve(raw: str, hook_input: dict[str, Any]) -> Path:
        path = Path(raw)
        if path.is_absolute():
            return path
        cwd = hook_input.get("cwd")
        return Path(cwd) / path if isinstance(cwd, str) and cwd else path
```

The daemon stats and reads the `--body-file` target with no containment test —
absolute, `..`-escaping and symlinked paths all resolve and are read. The
refusal messages disclose existence and `errno` (`:332`, `:341`) and, on the
oversize branch, the **exact byte size** (`:334-336`).

**Why an observation rather than a finding**: the agent named the path in its
own Bash command, so it could read the file itself; nothing is gained except
against paths the daemon itself bars. `verify_document`
(`issue_report/provenance.py:119-192`) never echoes body content, so there is no
content oracle. For `secret_file_guard`-protected paths the route is closed —
`R-SECRET-BASH-MENTION` matches the command text
(`secret_file_guard.py:208-210`).

**But the reason it is closed is an accident worth writing down.** Both
handlers sit at `Priority = 14`, and ties break **alphabetically on
`handler.name`**, which is the `display_name` (`core/handler.py:147`,
`core/chain.py:351`). `block-secret-file-read` sorts before
`issue-filing-gate`, and `secret_file_guard` is terminal
(`secret_file_guard.py:162`), so the chain ends before the gate reads anything.
Rename either display name and the ordering flips silently, and the gate would
read a protected file's bytes ahead of the guard whose contract is that they
are *"NEVER read into context by any route"*.

`constants/priority.py:72-76` asserts of this band: *"Relative order does not
change any verdict since all four in this band match disjoint hazards."*
**That assertion became false in this interval**, when `ISSUE_FILING_GATE` was
added to the band (`:84-90`): it and `SECRET_FILE_GUARD` both match a
`gh issue create` against the upstream tracker whose `--body-file` names a
protected path.

**Detector hypothesis**: for each priority value with more than one handler,
assert either that the members' `matches()` predicates are provably disjoint or
that the intended order is declared explicitly rather than inherited from the
display name. A corpus-style Defence (one recorded invocation per asserted
disjointness) is the honest form, since disjointness is not decidable from the
code. *Likely false positive*: bands whose members genuinely never co-match,
which is most of them — so the rule should assert the *declaration*, not the
property, in the manner of `check_declared_invariant_pairs.py`.

**Confidence**: high on the mechanism and on the `priority.py` comment now
being false; the ordering was traced through `chain.py`, `handler.py` and the
`HandlerIDMeta` display names rather than assumed. I did not execute the chain
to observe the order.

---

## Secondary observation B — the one-shot approval key sanitiser collides

**Citation**: `src/claude_code_hooks_daemon/utils/one_shot_approval.py:23-32`
(new file).

```python
#: Anything that is not a safe filename character becomes ``_``, so a key
#: like ``feature/x`` or ``../etc`` can neither collide by accident with a
#: plain name nor leave the store's directory.
_UNSAFE_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")
```

**Containment holds.** `/` can never survive the substitution, so the marker is
always a single filename component under `untracked_dir/<subdir>/`, and `..` is
separately mapped to `__`. The escape the comment claims to prevent is genuinely
prevented.

**The collision claim in the same comment is false.** `feature/x` normalises to
`feature_x`, which is exactly what the literal key `feature_x` normalises to.
Two branches differing only by `/` versus `_` share one approval marker, so a
human's one-shot approval for one is consumed by a gated action on the other
(`merge_to_main_approval` keys on the branch name).

**Severity**: low — it needs two branches whose names differ only in that
character. Reported because the docstring asserts the property it lacks, and a
comment that over-claims is how the next reader stops checking.

**Confidence**: certain on the mechanism, traced by hand through the regex and
the `replace`; low on it ever being reached.

---

## Examined and clean

Listed so that "looked at and sound" is distinguishable from "not looked at".

- **`install/truth_changes.py:574-577`** — `target = report_dir /
  _range_dirname(from, to)` followed by `target.glob("chunk-*.md")` and
  `stale.unlink()`. A glob-driven **delete** in a directory named from CLI
  arguments, which is the shape worth worrying about. Closed:
  `load_truth_changes_between` calls `parse_version_tuple`
  (`install/version_parse.py:30-45`) on both versions first, accepting only an
  optional `v`/`V` prefix and dot-separated integers, and the write is reached
  only when that parse succeeded and produced changes. No separator or `..` can
  survive.
- **`issue_report/citation.py:100-103`** — resolves the citation, *then* tests
  `is_relative_to(root / "src" / "claude_code_hooks_daemon")`, with the reason
  stated in a comment. Resolution-before-containment is the correct order: a
  symlink out is caught, and the prefix string test is explicitly not treated
  as the containment check.
- **`reference_repos/discovery.py`** — `os.scandir` with
  `entry.is_dir(follow_symlinks=False)`, depth-bounded, a checkout not
  descended into, a non-positive bound finding nothing. Deliberate and correct
  on every axis D-PATH asks about.
- **`bin/echd-capture` and `install/templates/echd-capture`** — a **fix** in
  this interval for exactly this check's class: the fixed
  `${TMPDIR}/echd-captures` name (pre-creatable as a symlink by another user on
  a shared host) became `mktemp -d …-XXXXXX`, unpredictable and 0700.
- **`strategies/lint/common.py:26-48`** with `kotlin_strategy.py` and
  `rust_strategy.py` — the same class, same interval, same fix: `kotlinc -d`
  and `rustc --out-dir` no longer name a literal path in the shared temp
  directory. No new fixed temp path is introduced anywhere in the delta (swept
  for `/tmp/`, `TMPDIR`, `gettempdir`, `tempfile.` across every added line in
  `src/`, `scripts/`, `bin/`).
- **`reference_repos/cache.py:68-70,134-137`** — under
  `daemon_untracked_dir(project_root)`. Contained.
- **`install/report_offload.py:88-100`** — joins an unsanitised `name` onto
  `report_dir`, but all three callers (`install/config_cli.py:246`,
  `install/truth_changes.py:583,600`) pass a constant or an
  `f"chunk-{number:02d}-{chunk.key}"` built from internal values. No external
  value reaches it today; a latent seam, not a defect.
- **`scripts/qa/check_github_urls.py`, `run_corpus_qa.py`,
  `run_pyright_check.py`** — new QA writers, all
  `root.joinpath(*_QA_OUTPUT_DIR_PARTS)` under an operator-supplied `--root`.
  Contained relative to the root the operator named.
- **`scripts/qa/run_smoke_test.sh:76`** — the one new shell redirect in the
  delta; `OUTPUT_FILE` is `${PROJECT_ROOT}/untracked/qa/smoke_test.json`.
  Contained.
- **`core/worktree_reaping.py`** (+246) — resolves `/proc/<pid>/cwd` symlinks,
  but is read-only and removes nothing (`:277-278`). Not a write site.
- **`install/install_stamp.py`** — read-only; the stamp write lives in
  `scripts/install/venv.sh`, untouched by this interval.
- **`utils/repo_relative_path.py`** — the `{REPO_ROOT}` expander rejects
  absolute, home-relative and `..`-carrying values (`:136-151`, `:188-189`).
  Correct.
- **`handlers/pre_tool_use/tdd_enforcement.py`** (+110) — the new casing loop
  substitutes two literals (`tests`, `Tests`); no external value enters a path.
  `_parse_test_path_map` rejects an absolute `test_dir` but **not** a `..` one
  — that code is unchanged since before `v3.63.0`, so it is out of this delta's
  scope and is recorded here only so a later full run does not treat it as new.

## Not attempted

No full-only check (`F-*`) was attempted, per the delta brief. In particular the
question "how many sites of Finding 1's class exist across `src/`" is a
whole-tree sweep, left to a full run or to the Defence that Finding 1 proposes.
