# Security review — D-DEP

**Check**: `D-DEP` — "Dependencies added or bumped in the interval, and what the
new code is trusted to do."
**Run**: Routine 00001, run 2026-001, FULL sweep.
**Interval**: root `74b0989cf254b24c3c713254b2c0b52ad5d7ed96` → HEAD `5d59f7ff`
(whole history, so: the current dependency set and what each is trusted with).
**Reviewer**: security-reviewer (opus), read-only.
**Findings**: 8 (1 high, 2 medium, 5 low/latent).

## Boundary held

This is a TRUST review, not a vulnerability review. No CVE lookups were
performed and no network request was made — that is `F-CVE`, a full-only check
on someone else's dispatch. Every claim below was established by reading this
repository and the packages already present in its QA venv on disk.

Two findings (D-DEP-01, D-DEP-06) touch surfaces that `D-EXEC` and `D-NET` also
review. They are reported here because the question I answer about them is
different: not "is this spawn shaped safely" but "what third-party code does
this hand control to, and who pinned it". Flagged so the caller can dedupe.

## The dependency set, as it actually resolves

`pyproject.toml:28-40` declares 7 runtime dependencies. The installed closure
in the QA venv is **19 packages** (7 direct + 12 transitive):

```
annotated-types  attrs  jsonschema  jsonschema-specifications  markdown-it-py
mdformat  mdformat-gfm  mdit-py-plugins  mdurl  psutil  pydantic  pydantic-core
pyyaml  referencing  rpds-py  tomli  typing-extensions  typing-inspection  wcwidth
```

Four of these load **native code** into the daemon process: `pydantic-core`
(Rust), `rpds-py` (Rust), `psutil` (C), and `pyyaml`'s optional `_yaml` C
extension. A compromised wheel for any of them is arbitrary native code inside
the process that enforces every guard, before any Python-level check runs. That
is a statement of the trust boundary, not a finding — but it is the reason the
provisioning findings below matter more than their individual severity suggests.

`uv.lock` holds 139 packages and is genuinely authoritative for the runtime and
dev sets: `--frozen` is passed on every sync path (`scripts/install/venv.sh:774, 782, 800`; `scripts/venv-include.bash:176`; `.github/workflows/qa.yml:116, 367`;
`scripts/setup_worktree.sh:154`), `uv lock --check` gates lock-vs-pyproject
drift (`scripts/qa/run_dependency_check.sh:40`), and `assert_venv_matches_lock`
gates installed-vs-lock drift (`scripts/venv-include.bash:217`). The reasoning
recorded at `scripts/install/venv.sh:756-767` is correct and the discipline is
better than most projects of this size. The findings below are the places that
discipline does not reach.

---

## D-DEP-01 (HIGH) — the daemon executes the guarded project's own npm toolchain, and calls it "trusted"

**Citation**: `src/claude_code_hooks_daemon/handlers/post_tool_use/validate_eslint_on_write.py:296-327`

```python
command = [
    "tsx",
    "scripts/eslint-wrapper.ts",
    file_path, "--max-warnings", "0", "--human",
]
cwd = str(workspace_root)
...
existing = [bin_dir for bin_dir in workspace_bin_dirs if bin_dir.exists()]
if existing:
    prefix = os.pathsep.join(str(bin_dir) for bin_dir in existing)
    env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
...
subprocess.run(  # nosec B603 - eslint/npx are trusted tools, file path validated
```

`workspace_bin_dirs` is the guarded project's own `node_modules/.bin`
(`:46`, `:170`, `:175`).

**What it concretely allows**: in a client project whose `package.json`
contains any `llm:` script (`:255`), every `Write`/`Edit` of a `.ts`/`.tsx`
file — and every Bash-authored one, when `check_bash_writes` is on (`:212`) —
causes the daemon to run `tsx` resolved from **that project's
`node_modules/.bin`**, executing `scripts/eslint-wrapper.ts` **from that
project's tree**, which in turn loads that project's ESLint, its flat config
(`eslint.config.js` — executable JavaScript), and its whole plugin graph. None
of that is shipped by this repository: `eslint-wrapper.ts` appears nowhere in
the tree or in `[tool.setuptools.package-data]`. So an attacker who lands a
malicious package anywhere in a guarded project's npm dependency tree gets code
execution in a daemon subprocess the next time anyone writes a TypeScript file,
with no prompt, no permission check, and no record — triggered by the security
daemon itself.

The `nosec B603` comment is the finding's core: it suppresses bandit by
asserting "eslint/npx are trusted tools". The *tool names* are trusted; the
*binaries those names resolve to* are supplied by the tree under review. Bandit
was told the wrong thing and stopped asking.

**The class**: a guard that, to make its decision, executes a program resolved
from the very tree it is guarding. Membership test: does the daemon spawn
something whose path is resolved through a directory the guarded project
controls (its `node_modules/.bin`, `vendor/bin`, `.venv/bin`, a `Makefile`
target, a repo-local script)? If yes, the guarded project can choose what the
guard runs. This is distinct from spawning a system tool on a fixed `PATH`.

**Why the test suite does not catch it**: the tests stub `subprocess.run` or
assert on the constructed argv. `["tsx", "scripts/eslint-wrapper.ts", ...]` is
the correct argv under every threat model — the defect is in *what that name
resolves to at runtime in someone else's checkout*, which no unit test in this
repository can observe. There is no fixture project with a hostile
`node_modules`, and building one would be a supply-chain simulation rather than
a test.

**Detector hypothesis**: flag any `subprocess` call in `src/` where the
executable (argv[0]) is a bare name AND the same function mutates `env["PATH"]`
with a path derived from user/workspace input, or passes `cwd=` a
workspace-derived root. Require an adjacent machine-readable justification
naming what makes the resolved binary trustworthy. *Likely false positives*:
`git`, `gh`, `node` and `python` invocations that legitimately rely on `PATH`
and take a `cwd` for unrelated reasons — probably several per sweep in
`utils/git_repo.py` and the CLI. Mitigate by firing only when `PATH` is
*modified* in the same function, which is the narrow and genuinely unusual
signal; on the current tree that condition is met once, here.

**Confidence**: high on the mechanism (argv, PATH prepend, `cwd`, and the
absent wrapper file are all read directly). Medium on impact, because it
depends on a client project having both `llm:` scripts and a compromised npm
tree. **What would settle it**: a fixture project with a
`node_modules/.bin/tsx` that writes a marker file, confirming the daemon
executes it on a `.ts` write.

---

## D-DEP-02 (MEDIUM) — the build backend is unpinned, unlocked, and executes on every install

**Citation**: `pyproject.toml:1-3`

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"
```

**What it concretely allows**: `uv.lock` contains 139 packages and neither
`setuptools` nor `wheel` is among them (verified: `grep 'name = "setuptools"' uv.lock` → no match). uv builds this project's editable install in an isolated
build environment resolved **fresh from PyPI at sync time**, against the
unbounded `>=61.0`. Confirmed empirically: the QA venv's `site-packages`
contains no `setuptools`, `wheel` or `pkg_resources`, so build isolation is in
use and the build deps came from `~/.cache/uv/builds-v0`, not from the lock.

setuptools' build backend runs arbitrary Python at build time by design. So
every `uv sync --frozen` on a fresh checkout — including **every client
install**, via `create_venv_at_path` — downloads and executes an unpinned
setuptools, in the same step the project relies on for "nothing unrecorded
enters this environment". A single malicious setuptools release compromises
every install performed during its window, and `--frozen` does not see it.

This sits directly against the guarantee asserted at
`scripts/install/venv.sh:756-767`: *"a checkout whose two files have drifted
apart gets a package set nobody recorded, silently"*. That reasoning is right
about the 139 locked packages and silent about the build environment, which is
precisely a package set nobody recorded.

**The class**: a dependency that executes code during provisioning but is not
covered by the artefact the project treats as authoritative for provisioning.
Membership test: is there a package whose code runs on install, whose version
is not fixed by `uv.lock`? Build-system requires, `setup.py`, `uv` itself, and
`pre-commit`'s remote hook repos all qualify; ordinary runtime dependencies do
not.

**Why the test suite does not catch it**: every test runs in an environment
that was *already built*. The build environment exists for seconds during
provisioning, installs nothing into the venv, and leaves no artefact a test can
assert on. `uv lock --check` compares `uv.lock` against `pyproject.toml`'s
`[project.dependencies]` only — it never reads `[build-system].requires`, so
the freshness gate is structurally blind here and reports green.

**Detector hypothesis**: parse `pyproject.toml`; for each entry in
`[build-system].requires`, fail unless it uses `==` and the same name+version
appears in `uv.lock`. *Likely false positives*: near zero on this repository
(one `[build-system]` block, two entries). The real cost is maintenance — an
exact build-backend pin needs deliberate bumping, and a stale setuptools pin
eventually fails on a new Python. Worth reporting as a rule with a real
ongoing cost rather than a free one; the cheaper variant is to require only
an upper bound (`>=61.0,<Y`), which caps the blast radius without a bump
treadmill.

**Confidence**: high that the build deps are unlocked and unpinned (read from
both files; absence of setuptools in the venv confirms isolation). Medium on
uv's exact caching semantics across repeat syncs. **What would settle it**: a
sync with an empty `~/.cache/uv` while watching network resolution, or
`uv build --verbose` showing the build environment's resolution.

---

## D-DEP-03 (MEDIUM) — mdformat imports every installed plugin into the daemon, not the one requested

**Citation**: `src/claude_code_hooks_daemon/utils/markdown_format.py:21, 81-84`

```python
_MDFORMAT_EXTENSIONS: Final[set[str]] = {"gfm"}
...
formatted_body = mdformat.text(
    body,
    extensions=_MDFORMAT_EXTENSIONS,
    options=_MDFORMAT_OPTIONS,
)
```

`{"gfm"}` reads as a closed allowlist. It is not one. In the installed
mdformat 1.0.0, `mdformat/_util.py:39` does
`mdformat.plugins.PARSER_EXTENSIONS[name]`, and that module attribute is
produced by `mdformat/plugins.py:__getattr__`, which calls
`_load_entrypoints(importlib.metadata.entry_points(group="mdformat.parser_extension"))`
— and `_load_entrypoints` does `ep.load()` for **every** entry point in the
group, before any name is selected. The same happens for
`mdformat.codeformatter`.

**What it concretely allows**: the first time the daemon formats any markdown,
every distribution in its venv declaring an `mdformat.parser_extension` or
`mdformat.codeformatter` entry point is imported, and its module-level code
executes inside the daemon process. `extensions={"gfm"}` narrows only which
loaded plugin is *used*. The trigger is routine: `markdown_table_formatter`
(PostToolUse, fires on every `.md` Write/Edit), the CLAUDE.md injector
(`core/claude_md_injector.py:468`), `docs_qa/quotes.py:204` and
`daemon/cli.py:5080` all reach it.

There is **no live exposure today** — `mdformat-gfm` is the only installed
distribution declaring the group (verified across all `*.dist-info/entry_points.txt`
in the QA venv). The finding is that the trust boundary for the daemon process
is not "the dependencies we named" but "any distribution in the venv declaring
that entry point group", and nothing in the repository states this or checks
it. Adding any dependency — direct or transitive — that happens to declare an
mdformat plugin grants it unreviewed code execution in the guard process, and
the review that would catch it is a review nobody knows to do.

**The class**: a dependency that performs entry-point discovery, turning "what
we import" into "whatever is installed". Membership test: does a dependency
call `importlib.metadata.entry_points(group=...)` and load the results? If so,
the trust set is the venv, not the import list.

**Why the test suite does not catch it**: the tests assert on formatted
markdown output, which is identical whether one plugin or twenty were loaded.
Detecting this needs a test that installs a second plugin distribution and
observes it being imported — a test about the environment, not about the code,
and none exists.

**Detector hypothesis**: for each runtime dependency, scan its installed
package for `entry_points(group=` / `iter_entry_points`; where found, record
the group name in a checked-in allowlist alongside the distributions currently
permitted to populate it, and fail when the venv contains an unlisted one.
*Likely false positives*: low in count but the rule needs the venv present, so
it cannot run as a pure source lint — it belongs beside
`assert_venv_matches_lock`, not in `run_lint.sh`. A cheaper 80% variant is a
single hardcoded assertion that only `mdformat-gfm` declares
`mdformat.parser_extension`, which catches the realistic case at the cost of
covering only one group.

**Confidence**: high. The loading behaviour was read from the installed
`mdformat/plugins.py` and `_util.py` in this venv, not inferred.

---

## D-DEP-04 (LOW, latent) — a lock-bypassing install path survives, documented as supported

**Citation**: `scripts/install/venv.sh:891`

```bash
local pip_cmd="uv pip install -e $daemon_dir --python $venv_python"
```

**What it concretely allows**: `uv pip install` reads no lockfile. It resolves
`pyproject.toml:28-40`'s floors — `pyyaml>=6.0`, `pydantic>=2.5`,
`jsonschema>=4.0`, `psutil>=5.9`, `mdformat>=0.7`, `mdformat-gfm>=0.4` —
against PyPI, so this function provisions a **runtime** dependency set that
`uv.lock` never named, into the venv the daemon runs from. (For scale: the
locked `mdformat` is 1.0.0 against a `>=0.7` floor, and `mdformat-gfm` 1.0.0
against `>=0.4` — two major versions of range each.)

`install_package_editable` has **no caller** (verified across the whole tree,
excluding `.git`, `untracked/` and `CHANGELOG.md`), so this is latent, not
live. Two things keep it worth reporting:

1. `scripts/install/README.md:89` documents it in the install-library function
   table as "Runs `pip install -e .` in venv" — it reads as a supported helper,
   so the next provisioning path is invited to call it.
2. Plan 00346 saw it and accepted it, at
   `CLAUDE/Plan/Completed/00346-pin-qa-toolchain-versions/PLAN.md:143-146`:
   *"`install_package_editable` still runs `uv pip install -e <dir>`, which
   reads no lock — it installs the daemon package alone with no `dev` extra, so
   it provisions no QA tools."* That is true and answers a narrower question
   than the one that matters. The plan's scope was QA toolchain pinning, so
   "no QA tools" closed it; but the daemon package alone still drags in all
   seven runtime dependencies, unlocked, into the process that enforces the
   guards. The acceptance rationale is sound for its own plan and does not
   cover the runtime case — and it lives in a completed plan, so a reader of
   `venv.sh` sees only an ordinary helper.

This is exactly the "unaudited future provisioning path" that
`scripts/venv-include.bash:215` names as the reason
`assert_venv_matches_lock` exists — and that assertion runs only in
`scripts/qa/run_dependency_check.sh:56`, which no client project ever executes.

**The class**: a provisioning path that installs this project's packages
without consulting `uv.lock`. Membership test: does the command install from
`pyproject.toml` or a requirements set rather than the lock? `uv pip install`,
`pip install -e`, `pip install -r` qualify; `uv sync --frozen` does not.

**Why the test suite does not catch it**: dead code. Nothing calls it, so no
test exercises it, and coverage exclusions for shell make its absence invisible.
The defect is that it is *available*, which is not a runtime property.

**Detector hypothesis**: grep `scripts/` and `install.py` for
`pip install`/`uv pip install` outside a documented escape hatch, and fail
unless the line carries an inline justification. *Likely false positives*: the
`HOOKS_DAEMON_ALLOW_UNLOCKED_VENV` branch at `scripts/venv-include.bash:190-192`
(deliberate, loud, documented) and the instructional strings in
`scripts/qa/run_semgrep_check.sh:39` and `daemon/server.py:637`, which print
`pip install` advice rather than running it. Three known exemptions for one
live catch — noisy for its yield, and worth landing as a warn rather than a
block.

**Confidence**: high on the facts (no caller, no lock read, README entry, plan
rationale all read directly). The severity call — latent, not live — is the
judgement, and it flips the moment anything calls it.

---

## D-DEP-05 (LOW) — three dev dependencies nobody runs, and the check that would say so is switched off

**Citation**: `pyproject.toml:51-53` and `pyproject.toml:289`

```toml
    "safety>=2.3",
    "build>=1.0",
    "twine>=4.0",
...
ignore = ["DEP002", "DEP003"]
```

**What it concretely allows**: nothing in the repository invokes `safety`,
`twine` or `build` — not `scripts/`, not `.github/workflows/`, not `bin/`, not
the release skill, not `CLAUDE/development/`. They are installed into every
developer and CI venv by `uv sync --all-extras` and never executed. Measured
transitive footprint in the current venv: **safety 47 packages, twine 31,
build 6** — roughly 84 distributions (before overlap) whose only role is to be
present. Each is a wheel that could execute at import and a name that could be
taken over, bought for no benefit.

`safety` is the one that costs twice. It is a dependency-vulnerability scanner.
Anyone reading `pyproject.toml` — or reviewing this project's security posture
— would reasonably conclude a dependency CVE scan exists. None does; `F-CVE`
is a manual full-only check precisely because nothing automated covers it. A
declared-but-never-run security tool is a control that reads as present.

`ignore = ["DEP002", ...]` at `:289` is why nobody notices. DEP002 is deptry's
*unused dependency* rule — the exact finding — and the comment justifying the
suppression ("dev tools (CLI-only, not imported in code) - false positives") is
correct about `black`, `ruff`, `mypy`, `bandit`, `pytest` and `pre-commit`,
which are genuinely invoked as CLIs. It is wrong about these three, which are
invoked by nothing. One blanket suppression covers both cases and cannot
distinguish them.

**The class**: a declared dependency with no invocation anywhere, where a
project-wide suppression prevents the tooling from reporting it. Membership
test: is the distribution neither imported in source nor named in any script,
workflow or documented command?

**Why the test suite does not catch it**: unused dependencies are not a runtime
property — the suite passes identically with or without them. The tool built to
catch exactly this (deptry, DEP002) is configured off project-wide at `:289`,
so the QA run reports green on a question it was told not to ask.

**Detector hypothesis**: for each `[dev]` entry, require either an import in
`src/`/`tests/`/`scripts/`, or a literal occurrence of the console-script name
in `scripts/`, `.github/workflows/` or `.pre-commit-config.yaml`; fail
otherwise. This is DEP002 plus a CLI-invocation search, which is what makes
the blanket suppression unnecessary. *Likely false positives*: a tool invoked
only through `pre-commit`'s `language: system`, and one whose console-script
name differs from its distribution name (`types-*` stubs, consumed by mypy
without ever being named). Both are enumerable and few; on the current tree
this rule fires exactly three times, all true.

**Confidence**: high that the three are uninvoked (searched every script,
workflow, skill and dev doc). The framing of `safety` as an implied-but-absent
control is my characterisation, not a mechanical fact — though it is the
reason to fix this rather than shrug.

---

## D-DEP-06 (LOW, dev-only) — `pyright==1.1.413` pins a downloader, not an analyser

**Citation**: `pyproject.toml:66-70`

```toml
    # The pyright QA gate (Plan 00368). The PyPI package wraps the npm
    # release and needs a `node` on PATH; pinned exactly because the gate
    # is zero-errors and a new pyright release can add diagnostics, which
    # must arrive as a deliberate bump, not as a red CI run one morning.
    "pyright==1.1.413",
```

**What it concretely allows**: the comment is accurate that the PyPI package
wraps the npm release, and the exact pin does achieve its stated goal — stable
diagnostics. What it does not say is what the pin does *not* cover. The
installed wrapper runs `npm install` at first use
(`pyright/_utils.py:28-71`) to fetch the npm `pyright` package into a cache,
and `pyright/node.py:83-96` invokes `nodeenv` to **download node binaries**
when none is on `PATH`. So the code that actually analyses this project is an
npm tarball plus possibly a node runtime, fetched at QA time, with no hash in
`uv.lock` and no integrity check by this repository. The wrapper also honours
`PYRIGHT_PYTHON_FORCE_VERSION` (`_utils.py:43`), so the version the pin
appears to fix is overridable from the environment.

Dev-only and correctly so: `create_venv_at_path` passes no `--all-extras`
(`scripts/install/venv.sh:774`), so no client venv receives it. The exposure is
developer and CI machines.

**The class**: a Python package pinned in `uv.lock` that is a thin wrapper
fetching its real payload from a second ecosystem at runtime. Membership test:
does the locked wheel download executable content on first use? `pyright`
qualifies; so would any `*-binary-wrapper` or `nodeenv`-backed package.

**Why the test suite does not catch it**: the QA gate asserts on pyright's
*verdict*, which is identical however the binary arrived. Nothing asserts where
it came from, and the npm cache lives outside the repository.

**Detector hypothesis**: maintain a small checked-in list of known
wrapper-style distributions and fail if one is added without a recorded note
about its second-ecosystem fetch. *Likely false positives*: high — "wrapper
that downloads a payload" has no reliable static signature, so this degrades to
a curated list that rots. I report this rule **as a weak one**: the honest fix
is a one-line note in `pyproject.toml` beside the pin saying what the pin does
not cover, not an automated check. A stronger mechanical variant, if wanted:
assert `PYRIGHT_PYTHON_FORCE_VERSION` is unset in
`scripts/qa/run_pyright_check.py` before invoking, which closes the override
half deterministically.

**Confidence**: high on the mechanism (read from the installed wrapper).
Deliberately reported as low severity: it is dev-only, and the pin does deliver
what its comment claims — the gap is between what the comment claims and what a
reader will infer.

---

## D-DEP-07 (LOW, dev-only) — the one remaining remote pre-commit repo is pinned to a mutable tag

**Citation**: `.pre-commit-config.yaml:22-23`

```yaml
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
```

**What it concretely allows**: `rev:` here is a git **tag**, which upstream can
move to any commit. pre-commit clones that repository and executes its hooks on
every `git commit` for any developer who ran `pre-commit install` — which
`CONTRIBUTING.md` instructs, and which `pyproject.toml:71-75` adds `pre-commit`
to the dev extra specifically to enable. Retagging `v6.0.0` upstream gives
arbitrary code execution on developer machines at commit time, and the
`--frozen` lockfile discipline does not extend to it — pre-commit resolves its
hook repos itself.

The irony is local: this file's own 20-line header (`:1-20`) is an essay about
deleting second version sources, written after mirror-repo pins drifted from
`uv.lock` for two years. Four hooks were correctly converted to `repo: local`.
The one remaining remote repo kept a mutable ref, and the header does not
mention it.

**The class**: an externally-hosted executable dependency pinned by a mutable
reference rather than a content hash. Membership test: can the named ref point
at different content tomorrow without anything in this repository changing?
Tags and branches qualify; full commit SHAs and hash-verified artefacts do not.

**Why the test suite does not catch it**: pre-commit hooks run at commit time,
outside pytest entirely. No QA check parses `.pre-commit-config.yaml`, and the
config is valid by pre-commit's own schema — mutable refs are its normal,
documented style.

**Detector hypothesis**: parse `.pre-commit-config.yaml`; for every entry whose
`repo` is not `local` or `meta`, require `rev` to match `^[0-9a-f]{40}$`.
*Likely false positives*: essentially none, and the rule is 6 lines. The real
cost is ergonomic — `pre-commit autoupdate` rewrites SHAs back to tags, so the
rule will fire after every autoupdate and needs a documented re-pin step, which
is the kind of friction that gets a rule disabled. Worth landing with that step
written down beside it.

**Confidence**: high. Mechanism and blast radius are both plain from the file.

---

## D-DEP-08 (LOW) — a missing `jsonschema` silently disables input validation

**Citation**: `src/claude_code_hooks_daemon/daemon/server.py:627-641`, and
`src/claude_code_hooks_daemon/core/input_schemas.py:356-359`

```python
except ImportError as e:
    # TIER 2: Crash in strict_mode, log warning in non-strict
    handle_tier2_error(
        error=e,
        strict_mode=self.config.strict_mode,
        ...
        graceful_message="jsonschema not installed - input validation disabled",
    )
    return None
```

**What it concretely allows**: `strict_mode` defaults to `False`
(`config/models.py:1580-1583`). `_validate_hook_input` then returns `[]` for
every event (`server.py:655-656`) — indistinguishable from "validated, no
errors". So a venv where `jsonschema` fails to import runs the daemon with hook
input validation entirely off, announcing it once in a log nobody reads, while
every guard continues to report normal verdicts on unvalidated payloads.

`jsonschema` is a hard runtime dependency in both `pyproject.toml:31` and
`uv.lock`, so a lock-provisioned venv always has it — which is why this is LOW.
It becomes reachable through the paths above: an unlocked install
(`HOOKS_DAEMON_ALLOW_UNLOCKED_VENV=1`, `scripts/venv-include.bash:181-193`),
`install_package_editable` (D-DEP-04), or a partially-built venv. The
`except ImportError` shape also catches an ImportError raised *from inside* a
present-but-broken `jsonschema`, not only an absent one.

**The class**: a security control whose dependency is optional in code but
mandatory in metadata, degrading open when the two disagree. Membership test: is
a declared non-optional dependency imported inside a `try`/`except ImportError`
whose fallback weakens a check rather than refusing to run?

**Why the test suite does not catch it**: the suite runs with `jsonschema`
installed, so the `except` branch is exercised only by tests that mock the
ImportError — and those assert the graceful message is produced, which is the
implemented behaviour. The tests confirm the degradation works; nothing asks
whether it should be the default.

**Detector hypothesis**: flag `try: import X / except ImportError:` in `src/`
where `X` is a non-optional entry in `[project.dependencies]`. *Likely false
positives*: low — there are only 7 runtime dependencies, and a genuinely
optional import should not be declared mandatory. This is the cleanest
Detector in this report: small, precise, and it fires on exactly the confusion
it names. It fires twice on the current tree (`server.py:627`,
`input_schemas.py:358`), both true.

**Confidence**: high on the mechanism and the default. Low on practical
exploitability — this needs another failure first, which is why it is reported
last rather than not at all.

---

## Examined and clean

Reported so a later reader can tell "looked, found nothing" from "did not look":

- **YAML parsing**: all 24 load sites across `src/`, `scripts/` and
  `.claude/project-handlers/` use `yaml.safe_load`. No `yaml.load`,
  `FullLoader`, `UnsafeLoader` or `load_all` anywhere. Clean.
- **Vendored/bundled third-party code**: none. No `vendor/`, `_vendor/` or
  `third_party/` under `src/`, `scripts/`, `relay/` or `.claude/`.
- **semgrep**: runs fully offline — `--config` points at local
  `scripts/qa/semgrep/`, with `--metrics=off` and `--disable-version-check`
  (`scripts/qa/run_semgrep_check.sh:56-64`). No registry fetch. Its 63
  transitive packages are dev-only and it *is* invoked, so unlike D-DEP-05 the
  footprint buys something.
- **Lock authority for the 139 locked packages**: `--frozen` on every sync
  path, `uv lock --check` for lock-vs-pyproject, `assert_venv_matches_lock` for
  venv-vs-lock. The `HOOKS_DAEMON_ALLOW_UNLOCKED_VENV=1` opt-out is loud,
  documented, and consistently honoured by both the installer and the checker.
  Working as designed.
- **Client extras isolation**: `create_venv_at_path` passes no `--all-extras`
  (`scripts/install/venv.sh:774, 782, 800`), so no dev dependency — semgrep,
  pyright, safety, coverage — reaches a client project. Confirms D-DEP-05/06/07
  as dev-only.
- **mdformat config loading**: `mdformat.text()` does not read
  `.mdformat.toml`; only the CLI and `mdformat.file()` do. No TOML config
  parsing is reachable from the daemon's markdown path.

## One observation, below the reporting bar

`pytest-cov`'s `coverage` installs `a1_coverage.pth` into the QA venv's
`site-packages`. A `.pth` file executes at **every** interpreter start in that
venv, including every daemon start in this self-install checkout, and this one
runs `exec()` on an embedded string containing a bare `except: pass`. It is
gated on `COVERAGE_PROCESS_START`/`COVERAGE_PROCESS_CONFIG` being set, so it
no-ops in practice. Not filed as a finding: it is upstream coverage.py's
standard mechanism, it is dev-only (no client venv has it), and the project has
no reasonable lever over it. Recorded because it is a concrete instance of the
D-DEP-03 shape — a dependency obtaining code execution in the daemon process by
a route the import list does not show — and the next reviewer should not have
to rediscover it to reach the same conclusion.

## Cross-check against the register

`CLAUDE/Security/README.md` holds one category, *authored path resolution*,
with Detector `scripts/qa/check_authored_path_stat.py`. None of the eight
findings above belongs to it: that class is about stat predicates on joined
paths, and none of these involves path resolution. All eight are new classes.

If any is promoted to a register category, D-DEP-08's Detector is the one that
best meets the register's stated obligation — a real `scripts/qa/` check wired
into `run_all.sh`, precise, cheap, and with an enumerable false-positive set.
D-DEP-02's and D-DEP-07's are similarly mechanical. D-DEP-06's is not, and I
have said so in its entry rather than letting it look like the others.
