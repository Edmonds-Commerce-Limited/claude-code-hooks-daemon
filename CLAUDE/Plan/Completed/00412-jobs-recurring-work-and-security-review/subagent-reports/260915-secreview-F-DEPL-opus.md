# Security review — `F-DEPL` (full sweep, run 2026-001)

**Check**: `F-DEPL` — "Deployed artefacts in client installs against their
templates here." Full-only because "drift is a property of the other
repository's state, not of this diff."

**Interval**: current tree, root `74b0989cf254b24c3c713254b2c0b52ad5d7ed96` →
HEAD `5d59f7ff`.

**Reviewer**: `security-reviewer` (read-only). Nothing was edited, fixed or
committed.

**Findings**: 6.

---

## What could and could not be answered

`F-DEPL` names two questions and only one of them is answerable from here:

1. **What this repository causes to exist in a tree it does not control, and
   what governs that file's content, mode and replacement.** Fully answerable —
   the deploying code is in this tree. All six findings below are of this kind.
2. **Whether any particular client's deployed copy currently matches its
   template.** **Not answerable, by construction.** No client install is
   reachable from this session; the only install visible here is this
   repository's own self-install, which is the degenerate case (source and
   target are the same file for most artefacts). I did not run this half and am
   not reporting a clean result for it. The design's answer to that gap is
   itself a finding (F-DEPL-3): the drift comparison runs **in the client**, at
   SessionStart, and what it covers is the thing that can be audited from here.

---

## The deployment surface, enumerated

Assembled from `install.py`, `scripts/install_version.sh`,
`scripts/upgrade_version.sh`, `scripts/install/hooks_deploy.sh` and every
`deploy_*` entry point under `src/claude_code_hooks_daemon/install/`. "Vendor"
means under `.claude/hooks-daemon/`, which the installer git-ignores; everything
else lands in space the client owns, commits and lints.

| Deployed path (client-relative)                                            | Mode         | Written by                                      | Replacement rule                                  | Drift-checked     |
| -------------------------------------------------------------------------- | ------------ | ----------------------------------------------- | ------------------------------------------------- | ----------------- |
| `.claude/hooks/*` (30 forwarders + status-line)                            | 0755         | `hooks_deploy.sh:196-209`, `install.py:489`     | blind overwrite                                   | **no**            |
| `.claude/init.sh`                                                          | 0755         | `hooks_deploy.sh:263`, `install.py:657`         | blind overwrite                                   | **no**            |
| `.claude/settings.json`                                                    | preserved    | `install.py:718`, `utils/settings_repair.py:57` | merge, one-shot backup                            | registration only |
| `.claude/hooks-daemon.yaml`                                                | —            | `install.py:815`, `install_version.sh:502`      | kept if present (shell); replaced by `install.py` | no                |
| `.claude/skills/<skill>/**`                                                | source modes | `install/skills.py:49-61`                       | **rmtree + copytree**                             | **no**            |
| `.claude/agents/hooks-daemon-*.md`                                         | 0644         | `install/agent_assets.py:366-368`               | md5 ledger; customised never touched              | yes               |
| `.claude/rules/*.md`                                                       | 0644         | `install/directory_role_rules.py:489-490`       | ledger/classify                                   | **no**            |
| `.claude/ccy/claude-supervise.py`                                          | 0755         | `install/ccy_supervisor.py:189-190`             | blind overwrite                                   | **no**            |
| `.claude/ccy/ccy.env`                                                      | —            | `install/ccy_supervisor.py:242,246`             | appends an **armed** wrapper line                 | **no**            |
| `.claude/ccy/.gitignore`                                                   | —            | `install/ccy_supervisor.py:297`                 | appends whitelist exceptions                      | **no**            |
| `.claude/project-handlers/**`                                              | —            | `install.py:991`                                | seeded when absent                                | n/a               |
| `.claude/commands/*`                                                       | —            | `scripts/install/slash_commands.sh`             | deploy                                            | **no**            |
| `.claude/HOOKS-DAEMON.md`, `CLAUDE.md` section                             | —            | `generate-docs`, `core/claude_md_injector.py`   | regenerated                                       | docs-QA check     |
| `CLAUDE/core/*.core.md`                                                    | 0644         | `install/core_docs.py:384-395`                  | unconditional overwrite                           | yes               |
| `CLAUDE/Plan/mkplan.bash`                                                  | 0755         | `install/plan_workflow.py`                      | unconditional overwrite                           | yes               |
| `CLAUDE/Plan/_planlib.inc.bash`                                            | 0644         | `install/plan_workflow.py`                      | unconditional overwrite                           | yes               |
| `CLAUDE/Plan/_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md` | 0644         | `install/plan_workflow.py`                      | seeded when absent, never overwritten             | n/a               |
| `<daemon_root>/bin/hooks-daemon`, `bin/echd-capture`                       | 0755         | `install/bin_wrapper.py:57-80`                  | blind overwrite                                   | **no**            |
| `<untracked>/bin/hooks-relay` (+ `.route`, `.sha256`)                      | 0755         | `install/relay_deploy.py:242,342`               | blind overwrite                                   | **no**            |
| root `.gitignore`, `.claude/.gitignore`                                    | —            | `scripts/install/gitignore.sh`                  | append                                            | n/a               |

Two deploy paths run **outside** install/upgrade, on ordinary daemon start —
i.e. merely using Claude Code in a client project writes files:
`controller.py:391` (`deploy_agents_if_enabled`) and `controller.py:410`
(`sync_directory_role_rules_if_enabled`). A third, `settings_repair`, rewrites
`.claude/settings.json` at SessionStart (`hook_registration_checker.py:212-217`).

Executable artefacts: the forwarders, `init.sh`, the two `bin/` wrappers, the
skill `scripts/*.sh`, `claude-supervise.py`, `hooks-relay`, `mkplan.bash`.

---

## Finding 1 — the client-ownership manifest is enforced in one direction, and the client-facing document states the opposite

**Citation**: `src/claude_code_hooks_daemon/install/client_owned_assets.py:124-205`
(the manifest, six entries) against `CLAUDE/LLM-INSTALL.md:719-723`:

```
Every path in that table is asserted against
`src/claude_code_hooks_daemon/install/client_owned_assets.py` — the daemon's
single manifest of what it deploys into client-owned space — by a test that
fails if the two disagree. A new deployed asset therefore cannot reach you
undocumented.
```

Every test in `tests/unit/install/test_client_owned_assets.py` iterates **from**
`CLIENT_OWNED_ASSETS` (lines 33, 94, 104, 113, 122, 137, 149, 171, 195, 257).
None iterates from the deploy sites. The assertion is manifest → files and
manifest → document; there is no files → manifest direction, so a deploy that
was never declared satisfies every test by not existing to them.

**What it concretely allows** — these assets reach a client today, are absent
from both the manifest and the boundary table at `CLAUDE/LLM-INSTALL.md:710-717`,
and the client is told in the same breath that this cannot happen:

- `.claude/skills/docs-qa/scripts/{_locate-cli.sh,find-comment-blocks.sh,sweep.sh}`
  — three **shell** scripts, mode 0755, deployed by the same function
  (`skills.py:90-92` iterates *every* bundled skill dir) whose sibling output
  `.claude/skills/hooks-daemon/scripts/*.sh` **is** declared at
  `client_owned_assets.py:146-154`. Same language, same deploy call, same
  exposure to the client's `shellcheck`; one is declared and one is not.
- `.claude/rules/*.md` — ten files (`directory_role_rules.py:69,489-490`),
  deployed on **daemon start**. These are instruction files Claude Code loads
  into the client's agent context.
- `CLAUDE/core/*.core.md` — three files, overwritten unconditionally
  (`core_docs.py:384-395`).
- `CLAUDE/Plan/_planlib.inc.bash` — a daemon-owned **shell** library deployed
  beside the declared `mkplan.bash`, overwritten on every deploy.

The security consequence is not the lint noise the manifest was built for. It is
that **the inventory a client can consult before granting this tool write access
to their repository is incomplete, while asserting that it is complete.** An
incomplete inventory that says so is a smaller problem than one that promises
otherwise: a reader who audits the table has no way to learn that four more
categories exist, two of them shell and one of them agent instructions.

**The class** — *a guard that enumerates from the registry it is meant to
police*. A defect belongs here when the check's iteration starts at the
declaration rather than at the behaviour, so the failure mode "the behaviour
exists and was never declared" is structurally invisible. Decision rule for a
new case: ask what a completely empty declaration would do to the check. If the
answer is "pass", it is this class. This is the same shape as the Plan 00378
md5-compared-with-itself defect (`agent_assets.py:96-103`), which is the
strongest evidence it is a class and not an incident.

**Why the test suite does not catch it** — the suite contains a test named
`TestManifestDescribesRealFiles` and one named
`TestBoundaryIsDocumentedWhereAClientReadsIt`, and both pass, because both are
true: every declared entry resolves to real files and appears in the document.
The suite has no name for the untested proposition ("every deployed asset is
declared") and therefore nothing fails when it is false. The tests pass and the
promise at `LLM-INSTALL.md:723` is false at the same time.

**Detector hypothesis** — a QA check (`scripts/qa/check_deploy_declarations.py`)
that parses `src/claude_code_hooks_daemon/install/**` for the write primitives
(`write_text`, `write_bytes`, `copyfile`, `copytree`, `copy2`, `chmod`) whose
destination expression is rooted at a `project_root`/`daemon_root` parameter,
resolves each destination to a client-relative glob via the module's own path
constants, and fails when a glob is neither covered by a `CLIENT_OWNED_ASSETS`
entry, nor under `VENDOR_DIR`, nor on an explicit "client-owned after seeding"
exemption list.

*Likely false positives, and they are not small*: (a) seed-once assets
(`_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md`, the `.claude/project-handlers/`
examples) are genuinely the client's after creation and must not be declared
daemon-owned — they need the exemption list, which is itself an
exemption-accumulation surface (`F-EXPT`'s problem); (b) backup/snapshot writes
(`rollback.sh`, `_free_backup_path`) target client space legitimately; (c) the
destination of `resolve_relay_binary_path` is config-derived and cannot be
resolved statically. I estimate a first run at roughly 20-30 sites of which
4-6 are real, which is a ratio worth shipping only if the exemption list is
seeded in the same commit. **Reported as noisy on purpose.**

**Confidence: high.** The omissions were verified directly (`ls` of the deployed
`.claude/rules/`, `CLAUDE/core/` and the bundled `skills/docs-qa/scripts/`
against the manifest text and the `LLM-INSTALL.md` table). What would settle the
remaining uncertainty — whether any of the four are deliberately excluded for a
reason not written down — is a maintainer ruling on each.

---

## Finding 2 — `deploy_skills` deletes a client-owned directory that shares a bundled skill's name, with no provenance check, and the upgrade snapshot does not cover it

**Citation**: `src/claude_code_hooks_daemon/install/skills.py:49-61`

```python
def _deploy_one_skill(source_skill_dir: Path, project_root: Path) -> None:
    target_skill_dir = project_root / ".claude" / "skills" / source_skill_dir.name
    ...
    if target_skill_dir.exists():
        shutil.rmtree(target_skill_dir)
    shutil.copytree(source_skill_dir, target_skill_dir, dirs_exist_ok=False)
```

Contrast, 40 lines below in the same module, `skills.py:96-121` — the **retired**
skill path:

> Only removes a directory whose `SKILL.md` carries the retirement's provenance
> marker. A same-named directory the daemon did not write is left alone with a
> WARNING naming the collision: deleting it would destroy project work with no
> backup, which is far worse than leaving an orphan slash command in place.

The reasoning is correct and is applied to the name the daemon *no longer*
ships, while the names it *does* ship — `hooks-daemon` and, since Plan 00284,
`docs-qa` — get the unconditional `rmtree`.

**What it concretely allows** — a project that has its own
`.claude/skills/docs-qa/` (a generic name for a generic task; the daemon chose
it for exactly that reason) loses that directory and everything in it on the
next daemon install or upgrade. Not overwritten file-by-file: `rmtree`, so files
with no counterpart in the bundle are gone too. Recovery depends entirely on the
client having committed it, because the upgrade's state snapshot
(`scripts/install/rollback.sh:158-177`) backs up `hooks-daemon.yaml`,
`settings.json`, `init.sh` and `.claude/hooks/*` — **and nothing under
`.claude/skills/`**. The console line is `"Skill deployed successfully to ..."`.

**The class** — *a destructive deploy whose collision test is the file's
location rather than its provenance*. A defect belongs here when the deploy
decides "this is mine to replace" from a path that lives in a namespace the
client also populates. The distinguishing question: could a file the daemon
never wrote occupy this path? For any flat, client-owned namespace —
`.claude/skills/`, `.claude/agents/`, `.claude/commands/` — the answer is yes,
which is why `agent_assets` uses an md5 ledger and `_remove_retired_skills` uses
a marker. `_deploy_one_skill` uses neither.

**Why the test suite does not catch it** —
`tests/claude_code_hooks_daemon/install/test_skills.py` has both halves of the
question and answers only one. `test_leaves_a_same_named_skill_the_daemon_did_not_write`
(line 303) asserts precisely this protection for the *retired* name, and its
docstring states the principle in full ("deleting work the daemon never wrote,
with no backup and only an info-level log line"). Meanwhile
`test_deploy_skills_overwrites_existing` (line 114) pre-creates the target with
a daemon-shaped `SKILL.md` and asserts the clobber — so the suite **ratifies**
the unconditional replacement for currently-bundled names, having never asked
who wrote the directory it pre-created. The tests pass; the asymmetry is in
them, not merely undetected by them.

**Detector hypothesis** — a check that flags any `shutil.rmtree` /
`Path.unlink` in `install/**` whose target path is built from a client-owned
namespace constant (`.claude/skills`, `.claude/agents`, `.claude/commands`,
`.claude/rules`) unless the enclosing function also reads the target's content
(a provenance marker, a digest, a version ledger) before the deletion.
*Likely false positives*: deletions of a path the same function just created
(temp/staging), and `remove_agent`, which does classify first but through a
helper — a purely syntactic version of this rule would need to follow one call
to see that. Low volume: there are few destructive calls in `install/**`, so
this rule is cheap and quiet, unlike Finding 1's.

**Confidence: high** that the code path is as described and that nothing backs
the directory up. **Medium** on likelihood: it needs a client whose own skill
name collides with `docs-qa` or `hooks-daemon`. What would settle it: a search of
any real client installs for a `.claude/skills/docs-qa/` the daemon did not
write — which is the client-side half this check cannot run from here.

---

## Finding 3 — drift detection covers the artefacts that are read and skips every artefact that is executed

**Citation**: `handlers/session_start/deployed_artefact_drift.py:106-110`

```python
drifted = [
    *self._drifted_agents(project_root),
    *self._drifted_core_docs(project_root),
    *self._drifted_plan_tooling(project_root),
]
```

and the imports at lines 47-65 that fix that scope: `agent_assets`, `core_docs`,
`plan_workflow`. Nothing else is compared, by any handler, at any event.

Set against the surface table above, the comparison covers: 3 agent definitions,
3 core documents, `mkplan.bash`, `_planlib.inc.bash`. It does **not** cover:

- `.claude/hooks/*` — the 31 scripts Claude Code executes on every hook event,
  deployed by a blind `_strip_relay_guard_block "$source" > "$target"`
  (`hooks_deploy.sh:205`);
- `.claude/init.sh` — sourced by every one of them;
- `<daemon_root>/bin/hooks-daemon` and `bin/echd-capture` — 0755, blind
  `shutil.copyfile` + `chmod` (`bin_wrapper.py:76-77`), and both are named by
  the generated `CLAUDE.md` guidance as commands the agent should run;
- `.claude/ccy/claude-supervise.py` — 0755, blind `write_bytes`
  (`ccy_supervisor.py:189-190`);
- `<untracked>/bin/hooks-relay` — 0755, `exec`'d in the forwarder hot path;
- `.claude/rules/*.md` — instruction files, even though
  `directory_role_rules.py:438` already provides the `classify_rule` function
  the handler would need, in the same shape as `classify_agent`, which the
  handler does use.

**What it concretely allows** — a deployed executable that no longer matches
what this repository ships is invisible until someone runs an install or an
upgrade, which is also the moment it is silently replaced. Both directions of
the check's brief land here: a client edit to `.claude/hooks/pre-tool-use`
(a plausible thing to do — it is an un-ignored shell script in their own repo)
is overwritten on upgrade with no report that anything was replaced; and a
forwarder that drifted for any other reason keeps executing, un-flagged, for as
long as the client does not upgrade. The only thing standing behind it is the
upgrade snapshot at `rollback.sh:168-177`, which preserves the bytes in
`untracked/upgrade-snapshots/<ts>/` but is restored only on upgrade *failure*
and is never surfaced as "your customised hook was replaced".

Adjacent, and worth stating because it is the shape a reader would assume is
covered: `hook_registration_checker` validates the *registration* — that
`settings.json` names `bash …/.claude/hooks/{event}` — and never the content of
the file it names (`hook_registration_checker.py:229-234`,
`utils/hook_registration.py` `validate_hook_commands`). Registration integrity
and artefact integrity look like one property and are two.

**The class** — *a coverage set chosen by ownership-model convenience rather
than by blast radius*. The handler's own docstring explains its scope through
what makes comparison *meaningful* (lines 23-34: unconditional-overwrite vs
ledgered ownership), which is a real distinction — but every uncovered artefact
above is in the *unconditional-overwrite* category, the one the docstring calls
the easy case ("`deployed != template` IS drift, with no version ledger
needed"). A defect belongs to this class when an integrity check's scope
correlates with how easy the comparison was to write and anti-correlates with
what the artefact can do when wrong.

**Why the test suite does not catch it** — the handler's tests, and its single
acceptance test (lines 226-249), assert that what it *does* compare is reported
correctly and that a clean tree is silent. An absent comparison has no test to
fail; it appears in no diff, ever. This is `F-GAP`'s argument operating inside
`F-DEPL`.

**Detector hypothesis** — reuse Finding 1's deploy-site enumeration and assert
the complement: every enumerated deployed path is either present in
`deployed_artefact_drift`'s comparison set or carries a declared reason for
exclusion. *Likely false positives*: the forwarders are the hard case and a
naive rule gets them wrong — they are **generated per project** (the relay guard
bakes in absolute paths, `forwarder_generator.py:243-267`), so "compare the
deployed file with the template" is the wrong comparison and would fire on every
healthy install; the honest comparison is regenerate-and-diff, which the
generator already supports but at a cost this handler is not currently paying.
`hooks-relay` is a build artefact with no template at all, and its correct check
is the digest sidecar (Finding 6), not a byte comparison. A rule that ignores
those distinctions is noisy in exactly the places that matter most.

**Confidence: high** on the coverage set (read directly from the handler and
confirmed by grepping every `session_start` handler for `.claude/hooks/`).
**Medium** on the remediation being as simple as widening the list, for the
generated-forwarder reason above.

---

## Finding 4 — `install.py --force` replaces the client's security configuration and skips the backup precisely when overwriting is most likely

**Citation**: `install.py:822-830` and `install.py:987`

```python
    # Backup existing config if it exists
    if config_file.exists() and not force:
        ...
        config_file.rename(backup_file)
    ...
    config_file.write_text(config)
```

The write at line 987 is unconditional. The backup at 822 is not.

Sixty lines above, the same file documents this exact defect as fixed — for a
different artefact (`install.py:742-745`):

> Back up an existing settings.json, INCLUDING under `--force`. Backing up only
> when NOT forcing had it exactly backwards: `--force` reinstalls over an
> existing install, so it is the invocation most likely to be overwriting a
> customised file, and it was the one that overwrote with no copy at all.

**What it concretely allows** — `.claude/hooks-daemon.yaml` holds the client's
handler configuration: which guards are enabled, `exclude_paths`,
`extra_whitelist`, `secret_word_list_path`, and the `plugins:` block registering
their own project-level handlers. `install.py --force` replaces all of it with
the shipped default template (`install.py:857-985`) and, with `--force`, leaves
no copy. Even without `--force` the file is *replaced* (renamed to `.bak`, then
the default written), so a reinstall silently resets the security posture to
defaults and reports `"✅ Created .claude/hooks-daemon.yaml"` — a line that reads
as creation, not as a reset. Losing the `plugins:` block silently disables every
project-level handler the client wrote.

**Reachability, stated honestly**: `install.py` is deprecated
(`CONTRIBUTING.md:230`) and the current Layer 2 path does the right thing —
`scripts/install_version.sh:445-446` keeps an existing config and runs a
migration advisory over it. But `install.sh:123` still invokes
`python3 "$DAEMON_DIR/install.py" --force` unconditionally in its legacy
fallback, which fires for any tag predating Layer 2 (`CLAUDE/LLM-INSTALL.md:615`
tells users this is expected), and several `RELEASES/*.md` still document
running `install.py` directly. So it is reachable, on an old-tag install or by a
user following older release notes — not on the mainline path.

**The class** — *a fix applied to the instance rather than to the class*. A
defect belongs here when a named, understood failure mode was corrected at one
call site while a sibling call site in the same file, with the same shape and
the same consequence, was left. The test: does a comment in the codebase already
explain why this is wrong, about a different object?

**Why the test suite does not catch it** — `tests/unit/install/` contains
`test_installer_settings_backup.py` and `test_installer_settings_preservation.py`
(the regression tests for the settings.json half) and **no equivalent for the
config half** — nothing in `tests/` asserts anything about
`hooks-daemon.yaml.bak` or `create_daemon_config`'s backup behaviour. The class
was fixed; the Defence was written for the instance.

**Detector hypothesis** — a check over the installers for "a destructive write
whose backup is gated on a condition the write is not": any function containing
both a `rename`/`copy` to a `.bak`-suffixed path and an unconditional
`write_text`/`write_bytes` to the same target, where the backup sits under a
narrower condition than the write. *Likely false positives*: legitimate
one-shot-backup designs (`settings_repair.py:94` deliberately skips the backup
when one already exists — the write is repeated, the backup is not, and that is
correct). The rule must compare *which* condition, not merely notice that they
differ, which makes it fiddlier than it first looks.

**Confidence: high** on the code path and on the absence of a test. **Medium**
on severity, entirely because of the deprecated-entry-point reachability above.

---

## Finding 5 — the ccy supervisor is deployed **and armed** when the client has expressed no opinion, and a client-edited copy is overwritten without a drift check

**Citation**: `src/claude_code_hooks_daemon/install/ccy_supervisor.py:155-178`

```python
    flag = config.ccy.deploy_supervisor
    if flag is False:
        ...return result          # only an EXPLICIT false opts out
    target_ccy_dir = project_root.joinpath(*_CCY_DIR_PARTS)
    if not target_ccy_dir.is_dir():
        ...return result
    ...
    result.recommend_enable = flag is None
```

then unconditionally, at lines 189-190 and 199:

```python
        target.write_bytes(source.read_bytes())
        target.chmod(_SUPERVISOR_MODE)          # 0o755
    ...
    result.armed, arm_message = _arm_ccy_supervisor(target_ccy_dir)
```

and `_arm_ccy_supervisor` (lines 231-248) writes
`export CCY_CLAUDE_WRAPPER="…/claude-supervise.py --arm --"` into `ccy.env`,
creating the file when absent.

**What it concretely allows** — with the config key **absent** (the state of any
client who has never heard of this feature), the presence of a `.claude/ccy/`
directory is sufficient for the daemon to install a 0755 Python program and wire
it as the wrapper around every subsequent `claude` launch, in armed mode. Armed,
per the comment block it writes at lines 80-91, means the supervisor injects a
real `/compact` and a `continue` prompt into the user's interactive session.
That is a component whose capability is *writing input into the user's agent
session*, defaulting on by absence of configuration. The single gate is the
existence of a directory — a weaker signal than consent, since `.claude/ccy/`
may exist because a teammate committed it.

The arming logic is careful about a client who *has* a stance
(`_WRAPPER_EXPORT_KEY in content` → untouched, set or commented out), which is
the right instinct applied one step too late: it protects a stated opinion but
treats silence as assent.

Separately, and squarely in this check's second question: `target.write_bytes`
at line 189 is a blind overwrite. A client who edited their deployed
`claude-supervise.py` — say, to remove the injection — has it silently restored
on the next install or upgrade, with no drift report beforehand (it is not in
`deployed_artefact_drift`'s set, Finding 3) and no snapshot behind it
(`rollback.sh` does not cover `.claude/ccy/`). This is the "silent overwrite of
a customised security-relevant file" the brief names, in its purest form: the
file is, by the project's own description, security-relevant enough to warrant
the `ccy_supervisor_integrity` SessionStart handler.

**The class** — *a capability whose default is derived from the absence of a
decision*. A defect belongs here when a tri-state gate maps "unset" onto the
same branch as "enabled" for an action that increases reach, rather than onto
the same branch as "disabled" or onto an advisory. The distinguishing question:
if the client had read the config reference and deliberately chosen, would the
absent-key behaviour match the choice most of them would make?

**Why the test suite does not catch it** — `tests/unit/install/test_ccy_supervisor.py`
tests the tri-state as specified, and `None ⇒ deploy + arm + recommend_enable`
is the specification (`ccy_supervisor.py:15-20`). The tests confirm the design;
the finding is about the design. `ccy_supervisor_integrity.py:100-107` goes
further and encodes the same default in a handler comment ("An absent key
(`None`) still deploys+arms on upgrade, so it is NOT an inconsistency"). Nothing
is broken; the question is whether that default was ever a client's to make.

**Detector hypothesis** — a check over `config/models.py` for `bool | None`
option fields, asserting that each one's *consuming* code maps `None` to the
lower-capability branch, with a declared exception list for the cases where
"absent means on" is deliberate. *Likely false positives*: high. Plenty of
tri-states legitimately mean "not yet decided, behave as before", and several of
this project's `None` defaults are inert. A more targeted variant — restrict the
rule to options that gate a **write or an exec into client space** — would fire
on perhaps three sites and is the version worth building. As a general rule over
all tri-states, I expect it to be suppressed within a week, and I would rather
say so than ship it as clean.

**Confidence: high** on the behaviour (read directly, and the CHANGELOG entry
for Plan 00147 states it in the same terms). **This one is a judgement call, not
a defect**: the default is deliberate, documented and advisory-backed. I am
reporting it because "documented and deliberate" is exactly how an over-broad
default survives review, and F-DEPL's brief asks the question directly. A
maintainer ruling settles it.

---

## Finding 6 — the relay binary's integrity claim is same-origin, is never re-verified before execution, and the independent baseline the design names does not exist

**Citation**: `src/claude_code_hooks_daemon/install/relay_deploy.py:305-345` —
`SHA256SUMS` and the binary are fetched from the same host, over the same
channel, by the same `fetch_fn`:

```python
    sums_url = _release_asset_url(version_tag, SHA256SUMS_ASSET_NAME)
    sums_bytes = fetch_fn(sums_url)
    ...
    binary_url = _release_asset_url(version_tag, RELAY_ASSET_NAME)
    binary_bytes = fetch_fn(binary_url)
    ...
    if actual_digest != expected_digest:  # refuse
```

The module's own comment (`relay_deploy.py:49-54`) names the missing piece:

> so a downloaded relay reports "verified" without depending on a shipped
> `relay/SHA256SUMS.released` release manifest, **which nothing in the release
> pipeline populates today**.

Confirmed: `relay/` contains `build.sh`, `hooks_relay.rs` and `test_relay.py`
only — no `SHA256SUMS.released` — while `install/transport_probe.py:160`
resolves that path as its default source of truth.

**What it concretely allows** — three separable things:

1. The digest check is an **integrity** check (truncation, corruption, a proxy
   mangling the body), not an **authenticity** one. Anyone able to serve both
   assets — a compromised release, a compromised publishing account, a party
   able to terminate TLS for that host — passes it by construction. The word
   "verified", written into the `.sha256` sidecar and reported by the transport
   probe, reads stronger than what was checked.
2. The verification happens **once, at deploy**. The forwarder hot path
   (`forwarder_generator.py:263-267`) tests only `-x` before exec'ing:
   ```bash
       _rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-<baked path>}"
       if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then
           exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" ...
   ```
   The recorded digest is never compared again. The binary lives under
   `untracked/`, which is git-ignored — so a replacement there shows in no
   `git status`, trips no drift handler (Finding 3), and is exec'd on every
   hook event of every session.
3. The path is `${HOOKS_DAEMON_RELAY_BINARY:-…}` — an environment variable
   redirects what gets exec'd. I rate this the least of the three: anyone who
   can set the environment of the Claude Code process can already run code. It
   matters only as a second route to the same outcome as (2).

**The class** — *a recorded integrity fact that is never re-read at the moment
it would matter*. A defect belongs here when a check's result is persisted as
metadata and the consuming path uses a cheaper predicate (existence, mode) in
its place. The distinguishing question: between the verification and the use,
can the artefact change, and would anything notice?

**Why the test suite does not catch it** — `tests/unit/install/test_relay_deploy.py`
injects `fetch_fn` and asserts the mismatch path refuses, which is the behaviour
under test and is correct. No test could catch (1), because it is a property of
the trust model rather than of the code; and no test catches (2), because the
exec-time check lives in generated bash, in a different module, and nothing
asserts a relationship between the two.

**Detector hypothesis** — a check that pairs every deployed executable with a
verification predicate and fails when the exec site's predicate is weaker than
the deploy site's: for each `chmod(0o755)` in `install/**`, locate the string of
the deployed path in any generated script or `subprocess` call and assert the
invocation tests something content-derived. *Likely false positives*: most
deployed executables legitimately have no runtime verification and do not need
one (`mkplan.bash` is tracked in the client's git, which is a stronger control
than a digest re-check). A rule that cannot tell "tracked in git" from
"git-ignored build artefact" fires on all of them. Scoping it to *git-ignored*
deployed executables reduces this to one site — `hooks-relay` — which is
honest: the rule is really a one-instance assertion, and I would write it as a
targeted regression assertion rather than dress it as a class detector.

**Confidence: high** on (2) and on the absent `SHA256SUMS.released` (both
verified directly). **Medium-low on materiality**: `relay_source` defaults to
`null` and neither route ever runs implicitly
(`relay_deploy.py:367-368`, `install_version.sh:513-521`), so today this affects
only projects that opted into `relay_source: download`. What would settle it: how
many installs have done so — a client-side fact, unavailable here.

---

## Not findings — the controls that hold

Recorded because a register that lists only failures cannot be read for what is
covered:

- **Agent definitions** (`agent_assets.py`) are the model the rest of the
  surface should follow: a declared md5 per shipped revision, a historic ledger
  so a pristine-but-old copy upgrades while a customised one never does, a loud
  named warning instead of a silent skip, an explicit `--force` escape whose
  absence on the bulk path is the protection, and no silent deletion ever
  (`sync_agents:434-444` advises a command rather than removing). The declared —
  not derived — digest at lines 96-103 is the correct response to the Plan 00378
  self-comparison defect.
- **Core documents** solve the customisation problem structurally: the daemon
  file is overwritten wholesale and a separate *override* document is seeded for
  the client (`core_docs.py:223-246`), so there is no shared file to fight over.
- **`settings.json`** is treated as the client's throughout: read before the
  backup rename so nothing is lost (`install.py:727-740`), always backed up
  under `--force`, one-shot backup + atomic replace + `copymode` at
  `settings_repair.py:90-113` (the `copymode` fixes a real defect — the replace
  would otherwise hand a git-tracked file the umask's mode).
- **Registration self-heal is disclosed**: when SessionStart re-adds hook
  registrations it says so, names the events and names the backup
  (`hook_registration_checker.py:248-263`), and the opt-out is documented in the
  handler's own `CLAUDE.md` block. A client who removes a *wrapper* from an
  event that still exists is not overridden — repair is additive per event
  (`utils/hook_registration.py`, and the checker warns instead).
- **Deployed executable modes are explicit, never `chmod +x`**, with the
  reasoning written down at `hooks_deploy.sh:70-84`: 0755 stated literally so
  the installing user's umask cannot silently produce 0744 and a
  root-installs/user-runs pair cannot end up with inert hooks. Nothing deployed
  is world-writable. The one mode that is computed rather than stated
  (`skills.py:141-144`, `mode | S_IXUSR`) is fine in practice, because the
  bundled scripts are `100755` in git and `copytree` preserves it — I checked,
  and am recording it as checked-and-clean rather than leaving it to be
  rediscovered.

---

## Summary

| ID       | Finding                                                                                                           | Confidence | Materiality                     |
| -------- | ----------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------- |
| F-DEPL-1 | Ownership manifest enforced one-way; boundary doc promises otherwise; 4 undeclared asset categories reach clients | high       | high                            |
| F-DEPL-2 | `deploy_skills` rmtree's a name-colliding client directory with no provenance check, unsnapshotted                | high       | medium                          |
| F-DEPL-3 | Drift detection covers read-only artefacts, skips every executed one                                              | high       | medium-high                     |
| F-DEPL-4 | `install.py --force` resets `hooks-daemon.yaml` with no backup                                                    | high       | medium (deprecated entry point) |
| F-DEPL-5 | ccy supervisor deploys **and arms** on an absent config key; blind overwrite                                      | high       | judgement call                  |
| F-DEPL-6 | Relay binary: same-origin digest, never re-verified at exec, absent in-repo baseline                              | high       | low-medium (opt-in)             |

The common thread across 1, 2 and 3 is worth naming, because it is more useful
than any single finding: **this project reasons about deployment ownership
extremely well in prose, and the prose is ahead of the enforcement.** Each of
those three findings is a case where the correct principle is already written
down in the very module that violates it — the retired-skill docstring, the
manifest's own "passes by omission" warning, the drift handler's
ownership analysis. None of them needs a new idea; each needs the existing idea
applied in the direction that cannot be checked by iterating over what is
already declared.

**Register note** (not written by me, per the agent contract): if a category is
opened from this report, F-DEPL-1's class — *a guard that enumerates from the
registry it is meant to police* — is the one that generalises beyond deployment,
since Plan 00378's self-comparing md5 is already a confirmed second instance.
