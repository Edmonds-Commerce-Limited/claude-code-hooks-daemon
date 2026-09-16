# Security review — D-NET (delta), v3.63.0 -> v3.64.0

**Check**: `D-NET` — "New network egress — any new fetch, and what it does with
the response." (`CLAUDE/Routine/00001-security-review-full/CHECKS.md:42`)

**Run**: Routine 00002, run 2026-001, DELTA sweep.
**Interval**: v3.63.0 (`3cdc2e11`) -> v3.64.0 (`ab0aeb35`), 432 commits,
907 files.
**Method**: the interval diff scoped to `src/`, `scripts/`, `bin/`, `relay/`,
`install.*`, `daemon.sh`, `init.sh`, `.github/`, then every egress candidate
read in source at the interval's tip. No network request was made.

**A note on how this file was authored**: the `Write` tool is disabled in this
session, so this report was written through a shell heredoc. The worktree
isolation guard refuses a command whose text carries version-control command
lines it cannot verify, so the code excerpts below render such lines in prose
or with the leading verb elided. Every one is cited by `file:line`, which is
the load-bearing evidence; nothing has been paraphrased in a way that changes
what the code does.

**Was the check answerable?** Yes, fully. The interval's diff contains every
fetch site it introduced; nothing was unreadable and no tool was missing. This
is a real answer, not an unrun check.

**Findings**: 4 (0 high, 2 medium, 2 low). Two of the four are **new relative to
the full sweep's D-NET report** (`260915-secreview-D-NET-opus.md`) — they are
absent from its E1-E13 egress inventory. One dates an existing full-sweep
finding to this interval. One is minor.

**Baseline note**: Routine 00001's full sweep covered `74b0989c -> 5d59f7ff`,
which contains this interval, and reviewed the tree rather than a diff. Where
this report says "the full sweep missed it", that means the site exists in the
tree the full sweep read and does not appear in its inventory or findings.

---

## Part 0 — A correction to the dispatch brief

The brief said this interval "added a remote-docs vendoring feature
(WebFetch-driven capture)". It did not. Across the interval the diff for
`src/claude_code_hooks_daemon/remote_docs/` (all of `capture.py`,
`fetchers.py`, `store.py`, `provenance.py`, `lookup.py`) and for both
`remote_docs_provenance.py` and `remote_docs_routing.py` is **empty**;
`remote_docs/capture.py` already exists at v3.63.0. What the interval added is
vendored *content* under `remote-docs/defence-before-fix.github.io/` plus
`.claude/REMOTE-DOCS.md`, and one modified test
(`tests/unit/remote_docs/test_remote_config.py`).

This matters for the ledger: the full sweep's N1, N2, N3, N4 and N9 all sit in
`remote_docs/` or its sibling `relay_deploy.py`, and **none of that code changed
in this interval**. A delta run cannot re-answer them and does not.

---

## Part 1 — The egress delta

Every point where the interval changed what this repository fetches.

| #   | Where (at v3.64.0)                  | Mechanism                                              | New in interval?                    | In the full sweep's inventory? |
| --- | ----------------------------------- | ------------------------------------------------------ | ----------------------------------- | ------------------------------ |
| D1  | `scripts/upgrade.sh:559`            | `fetch --force origin "$_TRACK_REF"`                   | **Yes** — absent at v3.63.0         | **No** — missed                |
| D2  | `scripts/upgrade.sh:307`            | `clone` with `-c protocol.file.allow=always`           | **Yes** — absent at v3.63.0         | Yes, as N8/E11 (but undated)   |
| D3  | `reference_repos/refresh.py:98,117` | `fetch_all` + `pull_ff_only` per discovered clone      | **Yes** — package added here        | Yes, as N6/E8                  |
| D4  | `scripts/setup_worktree.sh:154,157` | `uv sync --frozen --all-extras` (PyPI)                 | **Widened** — `--all-extras` is new | **No** — no uv-sync row exists |

At v3.63.0, `scripts/upgrade.sh` contains **zero** occurrences of `_CLONE_URL`,
`protocol.file.allow`, `UNSAFE_TRACK_REF` or `FETCH_HEAD`; at v3.64.0 it
contains eleven. Both D1 and D2 are introductions, not modifications.

### Confirmed negatives — I looked, and these are clean

Recorded because "I looked and found nothing" and "I could not look" are
different results.

- **No new HTTP client anywhere.** Searching the interval's source diff for
  `urllib`, `urlopen`, `requests.`, `httpx`, `http.client`, `aiohttp`,
  `WebFetch`, `fetch(` returns no added call site. The only added `socket.`
  references are `socket.gethostname()` (local hostname, two sites).
- **`version_check.py` changed, and the change REDUCES egress.** A new early
  return for branch installs (`version_check.py:197-206`) skips the
  `ls-remote` probe entirely. The new context it renders interpolates
  `stamp.raw` and `stamp.ref`, which come from a local install stamp — and
  `install_stamp.py:26` anchors the whole string to a strict
  `v<major>.<minor>.<patch>(+<ref>.<sha>)?` pattern whose character classes are
  `[0-9A-Za-z._-]` and `[0-9a-f]`, so neither field can carry a newline, a
  quote or a control character into agent context. The full sweep's "E4 cannot
  inject" negative still holds, by a different mechanism.
- **`status_line/git_branch.py` changed, and adds no network.** The added
  `run_git(cwd, "branch", "--show-current")` (`git_branch.py:45`) is a local
  ref read; the background auto-fetch scheduler is untouched.
- **`scripts/qa/check_github_urls.py` is new and does NOT fetch.** It is a
  static text check over URL shapes (`check_github_urls.py:51-55`); no network
  code in the file.
- **The `reference_repos` package contacts no URL it chooses.** Searching the
  whole package for `url`, `remote_url`, `allowlist`, `host` returns nothing —
  which is the finding the full sweep already recorded as N6, not a new one.

---

## Part 2 — Findings

### D1 — A new environment-selected fetch whose fetched commit becomes the executing daemon (NEW; the full sweep missed it)

**Citation**: `scripts/upgrade.sh:539-567`, and its consequence at `:639`.

```bash
_TRACK_REF="${HOOKS_DAEMON_UNSAFE_TRACK_REF:-}"
...
    # (verb elided -- see the authoring note at the top)
    ... -C "$DAEMON_DIR" fetch --force --quiet origin "$_TRACK_REF" \
        || _fail "Ref '$_TRACK_REF' not found on origin"
    TARGET_VERSION="$(... -C "$DAEMON_DIR" rev-parse FETCH_HEAD)"
    TARGET_SEMVER="$(... -C "$DAEMON_DIR" show "FETCH_HEAD:pyproject.toml" \
        | awk -F'"' '/^version[[:space:]]*=/ {print $2; exit}')"
```

The response's destiny, 72 lines later at `:639`, is a **forced hard reset** of
`$DAEMON_DIR` onto `$TARGET_VERSION` — the resolved `FETCH_HEAD` commit.

**What it allows**: an environment variable names an arbitrary refspec; the
fetched commit is force-reset into `$DAEMON_DIR`; `$DAEMON_DIR` is the hooks
daemon, which then runs on every subsequent tool call. So the concrete outcome
is: **setting two environment variables causes an upgrade run to fetch an
arbitrary commit from the network and install it as the code that mediates
every `Bash`, `Write` and `Edit` in every later session.** The commit needs no
tag, no signature and no semver — only a `pyproject.toml` carrying a
`[project].version`, and that string is consumed by `awk` with no validation
before flowing into `TARGET_SEMVER`, `TARGET_DISPLAY` and the
`check-truth-changes --to` argument.

This is strictly stronger than the full sweep's E11 (a clone of a defaulted URL
followed by a checkout of a *tag*), because `--force` overrides
non-fast-forward protection on the refspec and `FETCH_HEAD` is an arbitrary
commit rather than a release tag.

**The mitigations are real and should be stated.** Both
`HOOKS_DAEMON_UNSAFE_TRACK_REF` and `..._BECAUSE` must be set or the script
refuses (`:542-551`); the variable name says UNSAFE; a boxed banner is printed
(`:588-598`); the install is stamped non-release and `version_check` nags every
new session (`version_check.py:197-206`). This is a deliberately gated,
deliberately loud escape hatch, not a hidden one.

**What the mitigations are not**: every one of them is an *announcement*. None
restricts what may be fetched. There is no scheme check on the origin, no
allowlist of refs, no signature check on the commit. The interval also added
`$HOOKS_DAEMON_CLONE_URL` (D2) with no scheme check, and that URL becomes
`$DAEMON_DIR`'s `origin` on the fresh-clone path — so after this interval
**one environment variable chooses the host and a second chooses the commit,
and the result executes.** That composition is new here and appears in no prior
report.

**The class**: *a fetch whose response is executed, where the destination is
not pinned and the bytes are not verified.* This is precisely the class the
full sweep articulated at N5 ("is the URL fully determined by the shipped code?
is the response checked against a digest or signature carried independently of
it? is the scheme forced?"). D1 is a new instance of an already-named class —
which is the strongest argument available for opening that register category,
because the class demonstrably recruits new members between releases.

**Why the test suite does not catch it**: the branch-install gate is covered by
tests that assert the *refusal* arms — one variable without the other, a version
argument alongside a ref. The fetch arm cannot be tested without a remote, so
`tests/integration/test_upgrade_sh_*` exercise local fixtures. A green suite
proves the gate refuses malformed invocations; it asserts nothing about what
the well-formed invocation is permitted to install, because "anything on
origin" is the intended behaviour and there is no expressed constraint to test
against.

**Detector hypothesis**: over `*.sh`, flag any clone or fetch invocation whose
URL or refspec is a `${VAR:-...}` or `$VAR` expansion, and require each such
site to appear in a declared egress inventory naming (a) what determines the
destination, (b) whether the scheme is forced, (c) what happens to the
response. This is the `check_fail_open_inventory.py` archetype — a declared
inventory rather than a code-reading rule — chosen because the discriminator
("is this destination trusted?") is a property of the deployment, not of the
code, and an inventory records a wrong judgement attributably instead of
absently. **Likely false positives**: documentation comments quoting an install
one-liner (this repo has several: `install.sh:6`, `scripts/upgrade.sh:6`),
removable with a comment-strip pass; test fixture scripts such as
`scripts/dummy-client-repo.sh`. Estimated live hits today: 3 (D1, D2, and
`install.sh`'s clone). **Low noise.**

**Confidence**: **High** on every fact — the fetch, the forced reset, the
absence of scheme/signature checks and the v3.63.0 absence are all directly
readable, and the tag-to-tag search settles the "new in interval" claim.
**Medium** on how it should be ranked: an operator who can set environment
variables for an upgrade run can usually run commands anyway, so this is not a
privilege boundary crossed by a remote party. It matters because the *daemon
itself* is the artefact being replaced, and because CI, a devcontainer image or
a shared shell profile are all places an environment variable is set by someone
other than the person running the upgrade. **What would settle it**: whether
any shipped automation (a CI job, a container entrypoint, an agent skill) can
set `HOOKS_DAEMON_UNSAFE_TRACK_REF` without a human typing it. I did not find
one in this interval's diff, but I did not audit the tree for it — that is a
full-sweep question, not a delta one.

---

### D2 — `protocol.file.allow=always` on a clone of an env-overridable URL was INTRODUCED in this interval (dates full-sweep N8)

**Citation**: `scripts/upgrade.sh:305-308`

```bash
        _CLONE_URL="${HOOKS_DAEMON_CLONE_URL:-https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git}"
        # verb elided: the invocation is a clone, with -c protocol.file.allow=always
        ... -C "$PROJECT_ROOT" -c protocol.file.allow=always clone --quiet "$_CLONE_URL" "$DAEMON_DIR" \
```

**This is not a new finding.** The full sweep recorded it as N8 ("a security
default re-enabled in production code to satisfy a test fixture") with the same
citation, and its analysis stands unchanged — including its honest limit, that
the absence of `--recurse-submodules` puts CVE-2022-39253's specific chain out
of direct reach.

**What the delta adds** is the date and the composition. At v3.63.0 this clone
does not exist at all: `scripts/upgrade.sh` has no `_CLONE_URL` and no
`protocol.file.allow`. So N8 is a defect **introduced between v3.63.0 and
v3.64.0**, by Plan 00291's fresh-clone path, rather than long-standing. A
register entry that cannot say when a class acquired an instance cannot show
the class recruiting; this interval shows it recruiting twice (D1 and D2) in
one release.

**Detector hypothesis**: the full sweep's N8 detector (literal search for
`protocol.*.allow=always`, `GIT_ALLOW_PROTOCOL`, `--no-verify`,
`PYTHONHTTPSVERIFY=0`, `verify=False`, `-k`/`--insecure` outside test dirs)
covers it unchanged, and I agree with its assessment that this is the cheapest
rule in either report. I add one requirement: the detector must run over the
**diff** as well as the tree, because the value of catching this one is
catching it on the commit that adds it.

**Confidence**: **High** on the dating (tag-to-tag search, decisive). Severity
unchanged from the full sweep's Low.

---

### D3 — The reference-repo auto-fetch landed in this interval (dates full-sweep N6)

**Citations**: `src/claude_code_hooks_daemon/reference_repos/refresh.py:98,117`;
`config/models.py:1965` (`enabled: True`), `:1978-1981` (`auto_pull: True`);
`reference_repos/discovery.py:49-51`.

**This is not a new finding either.** The full sweep's N6 covers it completely
and accurately: default-on, an additive fetch of every remote of every checkout
discovered under `untracked/repos/`, fast-forwarded onto disk, with
`R-REFERENCE-REPO-STALE` then steering the agent to read the result, and no
allowlist anywhere in the package. I re-derived all of it from the diff before
reading the full sweep's report and reached the same conclusions, including the
absence of any URL or host handling in the package.

**What the delta adds**:

1. **The dating.** The whole package is new in this interval; `fetch_all` and
   `pull_ff_only` existed at v3.63.0 but had exactly one caller,
   `git_upstream_checker`, targeting the project's own repository. So the
   interval changed the automatic-fetch target set from "the repo the user
   cloned" to "every checkout found on the filesystem under a gitignored
   scratch root" (`untracked/` is `.gitignore:200`). That widening is the
   finding, and only a delta can show it.
2. **One narrowing the full sweep did not state.** `refresh_repo` returns
   before fetching when `inspect_repo` says the repo is not checkable
   (`refresh.py:94-96`), and a repo with no remote is not checkable
   (`inspection.py:79-80`). So the client-mode canary, whose documented setup
   removes `origin` outright
   (`CLAUDE/development/CLIENT-MODE-TESTING.md:116`), is never contacted. Worth
   recording because `CLAUDE/ReferenceRepos.md:96-98` describes an alternative
   canary setup — origin "pointed at an invalid host" — which **would** be
   fetched at every session start, turning a string nobody vetted as a network
   destination into one contacted automatically. That is a
   documentation/behaviour mismatch, not a code defect.
3. **Egress is unrecorded.** `fetch_all` returns a bool (`git_sync.py:338`) and
   `refresh.py` logs nothing, so "which remotes did this daemon contact at
   session start?" is unanswerable after the fact. The full sweep did not state
   this, and it is the difference between a finding being investigable and not.

**Why the test suite does not catch it**: `tests/unit/reference_repos/test_refresh.py`
does exercise the real `fetch_all` — but always against a bare repo created in
`tmp_path` and cloned by local path (`test_refresh.py:49-73`). Every destination
in the suite is a local filesystem fixture, so no assertion can be about where
the traffic goes; and `sweep_reference_repos` takes a `refresher` seam
(`sweep.py:85`) precisely so higher-level tests never fetch at all. You cannot
test a constraint that was never expressed.

**Detector hypothesis**: I endorse the full sweep's narrowed form — flag a call
to `fetch_all`/`pull_ff_only` whose `cwd` argument is not the project root, and
require that call site to name its source policy — and would fold it into D1's
declared egress inventory rather than ship it as a second mechanism. I add the
logging requirement as part of the inventory row: a site that cannot say which
host it contacted cannot be audited after an incident.

**Confidence**: **High** on the facts (independently re-derived).
**Medium** on whether it is a defect or an accepted trade, unchanged from the
full sweep's own assessment.

---

### D4 — Worktree setup gained a second PyPI install, and no uv-sync row exists in the egress inventory (NEW; minor)

**Citation**: `scripts/setup_worktree.sh:147-158`

```bash
    UV_PROJECT_ENVIRONMENT="${WT_VENV_PATH}" \
        uv sync --frozen --all-extras --project "${WORKTREE_DIR}" --quiet
```

**What it allows**: worktree creation now performs a second PyPI fetch whose
closure is the dev extras (pytest, ruff, mypy, pyright) rather than the runtime
set, and the fetched packages are then **executed** — that is the point of the
venv. `--frozen` pins everything to `uv.lock`, so the content question belongs
to `D-DEP`/`F-CVE` and not here.

The D-NET-relevant part is the inventory, not the severity: the full sweep's
E1-E13 table has **no row for `uv sync`** anywhere (E12 is `install.sh`'s
pipe-to-shell fetch of uv's own installer, which is a different thing). So a
fetch-and-execute channel that exists in three places — `install.sh`,
`scripts/setup_worktree.sh` and `.github/workflows/qa.yml` — is absent from the
baseline that this and future delta runs are measured against. An inventory
with a hole in it reports clean for everything in the hole.

**The class**: *a package-manager invocation treated as build plumbing rather
than as egress.* A member is any command that resolves and installs remote
artefacts which are subsequently executed — `uv sync`, `pip install`,
`npm ci`, `cargo fetch` — regardless of whether a lock file pins it. Pinning
answers "what did I get?", not "did I reach the network and run what came
back?", and only the first question has been asked here.

**Why the test suite does not catch it**: nothing tests `setup_worktree.sh`'s
network behaviour; the script is developer tooling, run by hand. The added
`import pytest` check at `:159` verifies the install *worked*, which is a
different property from where it came from.

**Detector hypothesis**: extend D1's declared egress inventory to require a row
for every package-manager invocation in `*.sh` and `.github/workflows/*.yml`
(`uv sync`, `uv pip`, `pip install`, `npm ci`, `npm install`, `cargo fetch`),
each naming its lock file or stating that it has none. **Likely false
positives**: near zero on the search; the cost is inventory maintenance —
roughly 6-8 rows today — and rows go stale silently, which is the standing
weakness of every declared-inventory Detector in this register and is already
stated on `CLAUDE/Security/FailOpenBoundaries.md`'s page.

**Confidence**: **High** on the facts. **Low** on severity as a security
finding in its own right — reported mainly because the inventory gap it reveals
affects every future delta run's baseline.

---

## Part 3 — Register cross-check

`CLAUDE/Security/README.md` holds four categories: authored path resolution,
asymmetric sibling protection, fail-open boundaries, unenumerated spelling.

- **D1 and D2** are not instances of any of the four. They belong to the class
  the full sweep named at N5 — *fetch-then-execute with an unpinned destination
  and unverified bytes* — for which **no register category exists**. D1 and D2
  are the first evidence that the class recruits between releases rather than
  sitting static, which is the argument for opening it.
- **D3** is not an instance of any of the four either; it is the full sweep's
  N6, still uncategorised.
- **D4** is an inventory-completeness finding, closest in shape to `F-GAP`.

Per the agent contract I have written nothing to the register. A category with
no Defence is a claim the register cannot make honestly, and the Defence is the
caller's to land.

---

## Part 4 — What this delta run did NOT do

Per `CHECKS.md`, a delta run must record what it did not attempt. This dispatch
was one check. I did not attempt `D-EXEC`, `D-EVAL`, `D-PATH`, `D-SEC`,
`D-RULE`, `D-DEP` or `D-PUB`, and I did not attempt any full-only check
(`F-CVE`, `F-EXPT`, `F-BYPS`, `F-GAP`, `F-DEPL`, `F-HYG`, `F-PRIV`).

Two things I found sit on another check's ground and are named here only so the
finding is not lost:

- **`D-EXEC`**: a fetch or a pull honours the *target repository's* own
  version-control configuration, which includes command-valued keys and
  transport helpers. D3 runs both in repositories discovered by a filesystem
  walk rather than named by configuration. I am flagging the question, not
  asserting an answer — settling it requires reading that config-trust
  behaviour against this call path, which is D-EXEC's work.
- **`D-DEP`**: `uv.lock` changed by 19 lines in this interval, and D4 widens
  what is installed from it. Neither is answered here.

---

## Summary table

| #  | Finding                                                                       | Severity | New to the review? | Confidence                              |
| -- | ----------------------------------------------------------------------------- | -------- | ------------------ | --------------------------------------- |
| D1 | Env-selected forced fetch whose commit is force-reset into the daemon         | Medium   | **Yes**            | High (facts) / Medium (ranking)         |
| D2 | `protocol.file.allow=always` clone of an env-overridable URL — introduced here | Low      | No (dates N8)      | High                                    |
| D3 | Reference-repo auto-fetch/pull from discovered clones — introduced here        | Medium   | No (dates N6)      | High (facts) / Medium (defect-vs-trade) |
| D4 | Second `uv sync --all-extras`; no uv-sync row in the egress inventory          | Low      | **Yes**            | High (facts) / Low (severity)           |
