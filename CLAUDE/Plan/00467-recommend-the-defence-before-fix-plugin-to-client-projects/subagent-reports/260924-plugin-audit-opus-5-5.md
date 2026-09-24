# Plugin support audit: how the daemon copes with Claude Code plugins

Scope: the seven areas in the team-lead brief. Subject: the Defence Before Fix (DBF) plugin
0.1.1, installed at project scope, plus the `pyright-lsp` code-intelligence plugin already
enabled at user scope. Nothing in source, tests, config or docs was edited, and nothing was
committed.

Detail reports from the three forks this audit split into. They are gitignored, so any
evidence this report does not repeat is only in them:

- Areas 1 and 3: `untracked/agent-reports/260924-plugin-audit-agents-skills-opus-5-5.md`
- Area 4: `untracked/agent-reports/260924-plugin-audit-walkers-opus-5-5.md`
- Areas 2, 5 and 7: `untracked/agent-reports/260924-plugin-audit-hooks-settings-opus-5-5.md`

Probe scripts are in `untracked/scratch/plugin-audit/`. `probe.bash` and `probe-tool.bash`
send one synthetic PreToolUse payload through `.claude/hooks/pre-tool-use`.

**Tally: 8 defects (3 release-blocking), 16 gaps, and 13 areas checked and fine.**

**Environment note.** `/root/.claude` is a symlink to `/workspace/.claude/ccy`, so the plugin
cache, the marketplace clones and plugin data are all inside the project tree. Two
marketplaces are on disk: `defence-before-fix` is a git clone with a nested `.git`, and
`claude-plugins-official` is a snapshot with no `.git` (227 `.md` files). The plugin was not
live in the session that ran the probes, so every agent and skill verdict comes from a
synthetic payload.

**Side effect for the lead.** The probe payloads had no `synthetic_source` marker, and their
session ids (`plugin-audit-probe`, `plugin-audit-lsp-fresh-2` and the forks' own) match no
known synthetic shape. `daemon/synthetic_traffic.py` therefore classes them as REAL traffic
in `verdicts.jsonl`, including the Plan 00418 orchestrator record. Filter those sessions out
of any analysis of that record.

---

## Defects

### P1. DEFECT, RELEASE-BLOCKING: the next release would enable the DBF plugin in every client

- **Evidence**:
  - In dogfood mode, the tracked `.claude/settings.json` is also the template the installers
    ship. See `scripts/install_version.sh:302` and `scripts/upgrade_version.sh:155`, which
    set `SETTINGS_JSON_SOURCE="$DAEMON_DIR/.claude/settings.json"`, and
    `tests/unit/install/test_settings_sources_ssot_drift.py:10-11`.
  - Commit `b00ecd02` added `enabledPlugins` and `extraKnownMarketplaces` to that file.
  - On upgrade, `_merge_presence` (`install/settings_merge.py:285-297`) delivers any
    top-level key that is new in the template.
  - On a fresh install, `scripts/install/settings_deploy.sh:92-99` copies the whole file.
  - `git tag --contains b00ecd02` prints nothing, so this has not shipped yet.
- **Reproduction** (re-run by the coordinator; it agrees with the fork):
  ```
  git show v3.66.0:.claude/settings.json > old.json; cp old.json client.json
  untracked/venv-workspace-py311-81c29529/bin/python -c "from pathlib import Path; from claude_code_hooks_daemon.install.settings_merge import run_settings_merge as m; print(m(Path('client.json'), Path('.claude/settings.json'), Path('old.json')).report)"
  -> MergeReport(..., keys_delivered=('enabledPlugins', 'extraKnownMarketplaces'), ...)
  ```
  - A client that already has its own `enabledPlugins` keeps it, but still receives
    `extraKnownMarketplaces`, which prompts for trust and install.
  - The Python route (`install.py:724`) generates the file rather than copying it, so the
    install routes disagree.
- **Impact**: this contradicts Plan 00467's non-goal, "Installing or enabling the plugin in a
  client project automatically".
- **Candidate remedy**:
  1. Now: move the dogfood install to local scope (`settings.local.json`, which is
     gitignored), or strip the two keys from the template before tagging.
  2. Durable fix: stop the dogfood settings file from doubling as the client template. Either
     ship a separate template, or have the deploy and merge step strip a declared set of
     dogfood-only keys.
  3. Add a test that fails when the shipped template carries `enabledPlugins` or
     `extraKnownMarketplaces`.
  4. `plansDirectory` is a dogfood value in the same template, and it has already shipped.
     Review it under the same fix.

### P2. DEFECT, RELEASE-BLOCKING: plugin agents are invisible to the Plan 00460 read-only logic, and a Write-less plugin agent is told to Write

- **Evidence**:
  - `utils/subagent_tool_resolution.py:186-192` returns `None` ("unknown") for every plugin
    agent. The comment says they are "not cheaply resolvable". That is wrong:
    `<config>/plugins/installed_plugins.json` records each plugin's `installPath`, `scope`
    and `projectPath`.
  - Both DBF agents declare `tools: Read, Grep, Glob, Bash`, with no Write.
  - Both agent files tell the agent to write a file: `agents/conformance-reviewer.md:57-58`
    and `agents/independent-searcher.md:42`.
- **Reproduction** (coordinator re-ran the PreToolUse half). An `Agent` payload whose prompt
  declares a report path:
  - `subagent_type: Explore` gets `READ-ONLY AGENT DISPATCH (Plan 00460) ... has no Write tool`.
  - `subagent_type: defence-before-fix:conformance-reviewer` gets `{}`.
- **Reproduction** (fork, SubagentStop with a 9000-character reply):
  - The plugin agent is told "Write the full report to a file now, at this exact path".
  - With an `agent_id`, it misses the "Do NOT write your own copy via a Bash heredoc" warning
    that `qa-runner` gets.
  - A Bash heredoc is the plugin agent's only route to a file, and that route bypasses the
    content guards.
- **Candidate remedy**:
  1. Add a plugin tier to the resolver. It reads `installed_plugins.json` under the resolved
     config dir and keeps the plugins enabled in `enabledPlugins` for the matching scope; for
     `scope: project`, `projectPath` must also equal the project root.
  2. It walks `<installPath>/agents/**/*.md`. The scoped id is
     `<plugin>[:<subdir>...]:<name>` (vendored `sub-agents.md:193` and `:350`).
  3. It reuses `_can_write_from_frontmatter`.
  4. Unit-test it with a fake config dir.
  5. File a DBF upstream issue: grant `Write` to both agents, or have them return the report
     inline.

### P3. DEFECT, RELEASE-BLOCKING: `format-markdown` and `housekeeping` rewrite installed plugin files

- **Evidence**:
  - `daemon/cli.py:5251-5289` (`_iter_markdown_candidates`) walks with `os.walk`. It prunes
    nested git repos and `daemon.exclude_paths`, but ignores `.gitignore`.
  - `daemon/housekeeping.py:120-126` runs `format-markdown .` as a mutating step without
    confirmation.
  - Nested-git pruning protects only the DBF marketplace clone. It does not protect
    `cache/<plugin>/<version>/` or the `claude-plugins-official` snapshot, neither of which
    has a `.git`.
- **Reproduction** (coordinator re-ran it):
  - `bin/hooks-daemon format-markdown .claude/ccy/plugins --check` printed 173 `Would reformat`
    lines and exited 1.
  - Two of them are DBF's `skills/dbf/references/spec/tools/{php,ts}-qa-ci.md`.
  - On a scratch copy, `php-qa-ci.md` got 68 changed lines.
- **Impact**: a housekeeping pass would edit third-party files that Claude Code loads as
  prompts. The edit is silent, because the tree is gitignored.
- **Related**: `find-comment-blocks` (`docs_qa/comment_finder.py:54`) has the same cause. Its
  shipped guidance scopes it to `src/`, so its impact is lower.
- **Candidate remedy**:
  - Route the walker through the shared `git ls-files --exclude-standard` corpus helper being
    built for 00466 N9.
  - Always exclude the resolved Claude config dir when it lies inside the project.
  - Add a regression test: a gitignored, non-git directory that holds a malformed `.md`.

### P4. DEFECT (fix before the release is recommended; affects an in-tree config dir only): `markdown_organization` denies writes to user-scope Claude config and plugin data

- **Evidence**:
  - `markdown_organization.py:996-1018` resolves the path to `.claude/ccy/...`, which then
    matches none of the `.claude/agents|commands|rules/` allowances at `:366-378`.
  - Only the memory path has a raw-path special case (`:987-994`).
- **Reproduction** (coordinator re-ran it): a PreToolUse `Write` of `x` to
  `/root/.claude/plugins/data/defence-before-fix-defence-before-fix/spec/NOTE.md` is denied
  with `BLOCKED [R-MARKDOWN-WRONG-LOCATION]`.
- **Also denied** (fork):
  - `/root/.claude/agents/*.md`, `commands/*.md`, `rules/*.md` and `output-styles/*.md`
  - `/root/.claude/skills/<n>/SKILL.md`
- **Limits**:
  - The same Bash write (`echo hi > .../NOTE.md`) is allowed, as documented.
  - A client whose Claude home is outside the project is unaffected.
  - The deny text calls an Edit "a new `.md` file", and its list of allowed locations omits
    `.claude/skills/`.
- **Candidate remedy**:
  - Classify the RAW path before `resolve()`. Skip the project layout rules for anything
    under the Claude config dir (`$CLAUDE_CONFIG_DIR`, else `~/.claude`), and keep the
    memory policy as it is.
  - Add tests with a home symlinked into the project.

### P5. DEFECT (fix before the release is recommended): `lsp_enforcement` treats an environment variable as proof of LSP, and ignores the code-intelligence plugins that actually provide it

- **Evidence**:
  - The vendored `remote-docs/code.claude.com/docs/en/tools-reference.md:327` says: "Claude
    Code keeps the tool inactive until you install a code intelligence plugin for your
    language."
  - `handlers/pre_tool_use/lsp_enforcement.py:242-244` decides availability from
    `ENABLE_LSP_TOOL` alone, and `get_relevance` (`:232`) does the same. Nothing checks which
    LSP plugins are enabled, or whether one covers the language being searched.
  - The no-LSP advice at `:480-486` says only "Set ENABLE_LSP_TOOL=1". It never says to
    install a code-intelligence plugin.
  - This session has `ENABLE_LSP_TOOL=1`. Its user scope enables `pyright-lsp` (Python) and
    `phpantom-lsp` (PHP), and no TypeScript server.
- **Reproduction** (fresh session id, so the `block_once` count starts at zero):
  ```
  PreToolUse Grep {"pattern":"class RefreshSpecRunner","glob":"*.ts"}
  -> deny [R-LSP-SYMBOL-LOOKUP] "... LSP tool available for this lookup ... Suggested LSP
     operation: goToDefinition"
  ```
  The "available" claim is false for `.ts`. Claude Code "returns an error result for each LSP
  call on a file whose language server it can't start" (`tools-reference.md:329`). So the
  first symbol search of each session costs a wasted denial and a failed LSP call.
- **Candidate remedy**:
  - Resolve the enabled LSP plugins across user, project and local scope, using the same
    `installed_plugins.json` walk as P2. Read each plugin's declared server extensions.
  - Enforce only when a server covers the searched file type, taken from the glob or path, or
    from the project's dominant language.
  - Change the no-LSP advice to "install a code intelligence plugin for <language>".

### P6. DEFECT (general, surfaced by this audit; fix before the release is recommended): strict YAML parsing drops agent files that Claude Code loads

- **Evidence**:
  - `.claude/agents/code-reviewer.md:3` has `: ` inside its description, which
    `yaml.safe_load` rejects (`ScannerError: mapping values are not allowed here`).
  - The resolver therefore returns `None` for an agent whose `tools:` line has no Write.
  - Plugin descriptions are prose, so they are exposed to the same failure.
- **Reproduction** (coordinator re-ran it): a PreToolUse `Agent` payload with
  `subagent_type: code-reviewer` and a declared report path returns `{}`, where `Explore`
  gets the READ-ONLY advisory.
- **Candidate remedy**: when YAML fails, fall back to a lenient top-level
  `key: rest-of-line` parser for `name`, `tools`, `disallowedTools` and `isolation`.

### P7. DEFECT (low): `agent_isolation_advisor` ignores `isolation: worktree` declared in an agent's own file

- **Evidence**: `handlers/pre_tool_use/agent_isolation_advisor.py` `matches()` reads only
  `tool_input["isolation"]`. DBF's `conformance-reviewer` declares `isolation: worktree` in
  its frontmatter.
- **Reproduction**: `untracked/scratch/plugin-audit/agents-skills/isolation_probe.py` forces
  two live threads. With no call-level isolation, it advises isolation (`True`) for an agent
  that is always isolated. A live payload cannot reach this, because the registry holds a
  single thread.
- **Candidate remedy**: have the shared resolver (P2) return the frontmatter, not just
  `can_write`. Treat a definition that declares `isolation: worktree` as already isolated.

### P8. DEFECT (low, incidental, in a project-only handler): the orchestrator simulation's record contradicts its own contract

- **Evidence**:
  - The module docstring of `.claude/project-handlers/pre_tool_use/orchestrator_simulate.py:29-30`
    says blocking would deny "Never `Bash`".
  - `_would_deny` (`:320`) indeed never denies Bash.
  - Yet `handle()` (`:352-354`) tells every main-thread Bash call "main thread would have
    been denied".
- **Reproduction**: every Bash probe in P9 and P10 below returned
  `SIMULATED orchestrator-only mode (...): main thread would have been denied — Bash: bash ".../refresh-spec.bash" --offline`.
  An agent reading this could conclude that running a plugin skill's script from the main
  thread is forbidden.
- **Candidate remedy**: word the Bash case as "recorded (Bash is never denied)", or emit the
  "would deny" text only when `_would_deny` would be true with the switch on.

---

## Gaps

### G1. Plugin hooks bypass the daemon's hooks policy with no advisory (area 2)

- **Evidence**:
  - `hook_registration_checker.py:220-234` and `utils/hook_registration.py:150-203` read only
    `.claude/settings.json` and `settings.local.json`.
  - Nothing under `src/`, `scripts/` or `install.py` reads `enabledPlugins`,
    `installed_plugins.json` or `hooks/hooks.json`.
  - The fork's fake plugin (`untracked/scratch/plugin-audit/hooks-settings/fake-plugin/`) has
    PreToolUse, Stop and SessionStart hooks. Placed in settings.json, all three are flagged
    as bypassing the daemon. Delivered by a plugin, they draw nothing.
  - The upstream hooks docs say plugin hooks "merge with your user and project hooks" and
    that "all matching hooks run in parallel".
- **Candidate remedy**:
  - Add a SessionStart advisory, at most once per session and never blocking, that names each
    enabled plugin shipping hooks and the events they cover.
  - Allow a per-plugin acknowledgement to silence it.
  - Mirror it in `health`.

### G2. A plugin PreToolUse hook can rewrite a call after the daemon judged it (area 2, security-relevant; from the docs, not reproduced live)

- **Evidence**:
  - Per the upstream hooks docs, decision precedence is `deny > defer > ask > allow`, so a
    daemon deny always wins.
  - But `updatedInput` from a parallel plugin hook replaces the input, and only the
    permission rules are re-run on it. The daemon's guards saw the original.
  - The daemon never emits `updatedInput` itself (`bash_safe_mode.py:14-18`).
- **Candidate remedy**:
  - The G1 advisory should single out plugins that have PreToolUse hooks.
  - Optionally, a PostToolUse comparison of `tool_input` against the judged input, keyed by
    `tool_use_id`.
  - Document the limit in the security docs.

### G3. The Claude Code plugin docs are not vendored (area 2)

- **Evidence**: `find remote-docs -type f` holds only `sub-agents.md`, `tools-reference.md`,
  `prompt-caching.md` and `llms.md` from code.claude.com. The fork's summarising WebFetch of
  the hooks page came back truncated and dropped the precedence line that G2 relies on.
- **Candidate remedy**: `bin/hooks-daemon remote-docs add` for `plugins.md`,
  `plugins-reference.md`, `discover-plugins.md`, `plugin-marketplaces.md` and `hooks.md`.

### G4. The docs say hooks come from settings files and never mention plugin hooks (area 7)

- **Evidence**:
  - `CLAUDE/Code/HooksSystem.md:662-669` omits plugin `hooks/hooks.json`.
  - Its env table (`:719-724`) omits `CLAUDE_PLUGIN_DATA`.
  - `CLAUDE/ARCHITECTURE.md:80-96` does not list plugins as a live hook source.
  - `grep -i plugin CLAUDE/LLM-INSTALL.md README.md` finds no Claude Code plugin guidance: no
    scope choice, no note on what project scope means for collaborators, no trust gate, and
    no warning that plugin hooks bypass the daemon.
- **Candidate remedy**: add a "Claude Code plugins alongside the daemon" section, which is
  also where Plan 00467 Phase 2's recommendation belongs, and fix both tables.

### G5. "Plugin" means two different things (area 7)

- **Evidence**:
  - The daemon's own `plugins:` block (`.claude/hooks-daemon.yaml:1171-1173`) and
    `src/claude_code_hooks_daemon/plugins/loader.py` are unrelated to Claude Code plugins.
  - `CLAUDE/LLM-UPDATE.md:989`, `docs/guides/GETTING_STARTED.md:178` and
    `.claude/HOOKS-DAEMON.md:201` use the bare word.
- **Candidate remedy**: add a glossary line, and consistently write "daemon plugin (handler
  module)" versus "Claude Code plugin".

### G6. Nothing tells dogfood maintainers that `.claude/settings.json` ships to clients (area 5)

- **Evidence**: `grep -n settings.json CLAUDE/SELF_INSTALL.md` finds nothing. That is how P1
  landed unnoticed.
- **Candidate remedy**: a line in SELF_INSTALL.md, paired with the P1 test.

### G7. Claude Code is an uncounted, unlocked writer of settings.json (area 5, minor)

- **Evidence**:
  - `settings_merge.py:490-494` counts four unlocked writers. `/plugin` and
    `claude plugin install/enable/disable` are a fifth, and they reorder keys.
  - `utils/settings_repair.py:78-107` replaces the file without re-reading it, so a plugin
    install landing at the same moment could be lost.
- **Candidate remedy**: re-read before replacing, and correct the docstring.

### G8. `markdown_organization` has no notion of a plugin source layout (area 4)

- **Evidence**: Writes to `agents/*.md`, `commands/*.md`, `skills/<n>/SKILL.md` and
  `skills/<n>/references/*.md` at a plugin root are all denied with
  R-MARKDOWN-WRONG-LOCATION. The docstring at `markdown_organization.py:354` says SKILL.md is
  "allowed anywhere", but the code does not do that.
- **Candidate remedy**: treat a directory holding `.claude-plugin/plugin.json` or
  `marketplace.json` as a plugin root. Allow its component markdown, and fix the docstring.

### G9. The post-merge advisories judge a nested-repo pull against this repository (area 4)

- **Evidence**: `daemon_sync_after_merge.py:184-196` and `merge_qa_report.py:267-277` work out
  the repository from payload `cwd` only. `git -C .claude/ccy/plugins/marketplaces/<m> pull`
  is therefore judged against this project's `ORIG_HEAD..HEAD`.
- **Candidate remedy**: add both handlers to Plan 00464 Task 1.1's resolver audit list.

### G10. `project_containment` takes the Claude home from the daemon's environment (area 4, low)

- **Evidence**:
  - `project_containment.py:205-216` reads `CLAUDE_CONFIG_DIR` or `Path.home()` from the
    daemon process, so a session with a different home has its plugin data dir judged out of
    root.
  - The docstring's claim that reading it per call helps is wrong.
  - In this container, Write and Bash-redirect probes into `/root/.claude/plugins/data/...`
    are allowed. `/root/.cache/...` is denied with R-WRITE-OUTSIDE-PROJECT-ROOT, which is
    correct.
- **Candidate remedy**: fix the docstring, and consider allowing
  `*/.claude/plugins/data/**`-shaped paths or a declared list of Claude homes.

### G11. `lsp_noise_checker`'s exclude advice is hard-coded to the ccy directory name (area 4, narrow)

- **Evidence**: `constants/paths.py:113-126` has `CCY_PLUGINS_DIR`. An in-tree
  `CLAUDE_CONFIG_DIR` with any other name gets no exclude advice.
- **Candidate remedy**: derive the path from the resolved config dir.
  `check_skill_references.py:34`, which excludes a directory named `ccy`, has the same limit.

### G12. The size blocker's prescribed report path keeps the raw colon (area 1, cosmetic)

- **Evidence**: `subagent_report_size_blocker.py:122-127` prescribes
  `untracked/agent-reports/260924-defence-before-fix:conformance-reviewer-{model}.md`. The
  persister sanitises the colon to `_`, so the two names disagree.
- **Candidate remedy**: pass the agent type through the existing `_sanitise`.

### G13. The agent resolver hardcodes `~/.claude` (area 1)

- **Evidence**: `subagent_tool_resolution.py:177` ignores `CLAUDE_CONFIG_DIR`, which
  `project_containment` honours. P2's plugin tier needs the same answer.
- **Candidate remedy**: one shared `claude_config_dir()` helper, used by `project_containment`,
  the agent resolver, P3, P4, P5 and G11.

### G14. `skill-scan` does not know that plugin and user skills exist (area 3)

- **Evidence**: `skill_scan/digest.py:48-66` (`existing_skill_names`) and
  `skill_scan/constants.py:80-81` list only the project's `.claude/skills` and
  `.claude/commands`. It can therefore propose a skill that `/defence-before-fix:dbf` already
  covers.
- **Candidate remedy**: add the scoped names from enabled plugins, plus user skills.

### G15. Nothing measures a plugin's always-on context cost (areas 3 and 7)

- **Evidence**: `tool_report/costs.py:39-42` holds fixed per-tool constants only. Plan 00467
  Task 2.1 wants a "what it costs" field.
- **Candidate remedy**: a `tool-report` section that sums the description lengths of enabled
  plugins' skill and agent frontmatter and their MCP tool schemas.

### G16. No guard or advisory on editing installed plugin files (area 7, minor)

- **Evidence**: PreToolUse `Edit` of
  `/root/.claude/plugins/cache/defence-before-fix/defence-before-fix/0.1.1/agents/conformance-reviewer.md`
  (adding `Write` to `tools:`) is allowed silently, and so is an Edit in the marketplace
  clone. Such edits are lost on the next plugin update. They also silently change a trusted
  third-party prompt, and P2 makes this particular workaround tempting.
- **Candidate remedy**: a PreToolUse advisory, not a deny, on writes under
  `<config>/plugins/{cache,marketplaces}/`: "installed plugin file; changes are lost on update,
  so fork the plugin or file upstream".

---

## Checked and fine

- **F1. Area 6: the plugin's Bash use under daemon guards.** Every invocation shape was
  allowed, and the only context added was P8's simulation note:
  - `bash "<script>"`, `--offline`, `--force` and `2>&1`, by the `/root/.claude/...` path,
    the `/workspace/.claude/ccy/...` path and the relative path;
  - the unexpanded `"${CLAUDE_SKILL_DIR}/..."` form;
  - `DBF_SPEC_OFFLINE=1 bash ...`;
  - `bash ... | grep SPEC`.
  - A real offline run exited 0 and listed the five vendored documents.
  - A real network run (`CLAUDE_PLUGIN_DATA=untracked/scratch/plugin-audit/plugin-data ... --force`)
    exited 0 and fetched all five documents.
  - The script's `curl` and `mkdir`/`mv` writes happen inside the script, so the daemon
    judges only `bash <script>`.
  - Write probes of the script's full content to a new plugin-source path passed every
    content guard (`error_hiding`, `sed`, `tdd`, `security`). Overwriting the cached copy
    drew only the expected R-WRITE-CLOBBER.
  - Read, Grep and Glob over the plugin cache and data were all allowed.
  - A WebFetch of the canonical SPEC drew only the remote-docs "capture it" advisory.
- **F2. The spec copies agree.** SPEC 1.0.1, DETECTOR-SPEC 1.0.0 and TOOLING-SPEC 0.2.0 match
  across `remote-docs/`, the plugin's vendored copy and a fresh fetch. The plugin's vendored
  and fetched copies of SPEC and DETECTOR-SPEC are byte-identical. This is a Plan 00467
  Task 1.2 data point.
- **F3. Worktree and auto-save naming handle scoped names.** `core/worktree_naming.py` slugs
  `defence-before-fix:conformance-reviewer`, and `utils/subagent_report_paths.py:57-60`
  sanitises it. Plan 00464's resolver has not started. A worktree-isolated plugin agent that
  runs the project's QA entry point, as `conformance-reviewer` does, belongs in that plan's
  tests.
- **F4. No skill-name hijack.** Plugin skills are namespaced, and the project's
  `hooks-daemon` skill keeps its bare name. One residual belongs in the recommendation
  guidance: a plugin skill named `hooks-daemon` or `docs-qa` loses its bare alias in a daemon
  project.
- **F5. `tool_disable_advisor`, `session_actions_directive` and `check_skill_references`** do
  not list skills, or they already skip `ccy`. G11 covers the name-keyed limit.
- **F6. The `sensitive_content` tree scan and the git-history sweep** cover tracked files
  only. Both are clean.
- **F7. `repo_hygiene`**: nothing about plugins.
- **F8. `worktree-reap`**: the marketplace clone is not a worktree, so it is never listed.
- **F9. `secret_file_guard` and its hygiene checker**: plugins match no protected glob, and
  the `os.walk` fallback prunes `.git`.
- **F10. The nested-install and monorepo detectors** never treat the marketplace `.git` as a
  nested install. `validation.py:266-303` checks a literal path, and `monorepo_detector.py:70-82`
  skips dot-directories.
- **F11. `git_upstream_checker`** looks at the project root only. That is correct, because
  Claude Code owns marketplace updates.
- **F12. The three-way settings merge keeps a client's own plugin keys**, and the CLI's key
  reorder upsets nothing:
  - Three settings-merge test files: 58 passed.
  - `markdown_plan_sync` looks `plansDirectory` up by key.
  - `deployed_artefact_drift` does not compare settings.json.
  - A live SessionStart probe produced no hook-registration block.
- **F13. Always-on cost matches the plan.** The skill and agent descriptions total about 1.1k
  characters, roughly 290 tokens. The SKILL.md body is 7,106 bytes, about 1.8k tokens per
  invocation against a projected 1.6k.
  - Known issue 00466 N9, not re-reported, now has a number: plugin-path docs-QA lines are
    58% of the SessionStart `additionalContext` (5,991 of 10,333 characters).

---

## Fix before the next release

1. **P1** is release-blocking: strip the plugin keys from the shipped template, move the
   dogfood install to local scope, and add a test.
2. **P2** is release-blocking: add plugin agent resolution, and file the DBF upstream issue
   about Write-less agents that are told to write.
3. **P3** is release-blocking: stop `format-markdown` and `housekeeping` from walking
   gitignored and Claude-config trees. Share the N9 helper.
4. **P4, P5 and P6** are recommended before the release. P5 affects every client that sets
   `ENABLE_LSP_TOOL` and works in more than one language.
5. **P7, P8 and G1-G16** can follow in a plugin-support plan. A single shared
   `claude_config_dir()` / enabled-plugins resolver (G13) underpins P2, P3, P4, P5, P7, G1,
   G11, G14 and G15, and is the natural first task.
