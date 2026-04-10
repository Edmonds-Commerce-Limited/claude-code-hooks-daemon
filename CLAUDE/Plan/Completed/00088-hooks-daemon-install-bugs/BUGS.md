# Claude Code Hooks Daemon - Installation Bug Report

**Date**: 2026-03-13
**Daemon Version**: 2.4.0 (uv reported 2.21.1 during install — see Bug 3)
**Install Method**: Automated (`install.sh` via curl — Quick Install / recommended path)
**OS**: Linux 6.18.16-100.fc42.x86_64 (Fedora 42, Podman container / YOLO mode)
**Python**: 3.11.2 at `/usr/bin/python3`
**Project Path**: `/workspace` (10 chars)
**Git State at install time**: Brand new repo, `main` branch, no commits, no remote origin

---

## Bug 1 (Critical): Prereq checks are incomplete — daemon requirements not validated before install begins

The installer's Step 1 ("Checking prerequisites") only validates:

- `git` binary is present
- `.claude/` directory exists
- `.git/` directory exists

It does **not** check the conditions the daemon itself requires to operate. These are only
discovered later — silently — when the daemon fails to start at Step 11. The daemon requires:

| Requirement                    | Checked by installer? | What happens if missing       |
| ------------------------------ | --------------------- | ----------------------------- |
| `git` binary                   | Yes                   | Clear fail message            |
| `.claude/` dir exists          | Yes                   | Clear fail message            |
| `.git/` dir exists             | Yes                   | Clear fail message            |
| `git remote origin` configured | **No**                | Silent exit code 1 at Step 11 |
| Python 3.11+                   | Yes (Step 2)          | Clear fail message            |

The installer should do **nothing** if prereqs are not met. Instead it deployed 11 hook
scripts, settings.json, hooks-daemon.yaml, .gitignore entries, commands, and skills before
discovering the problem. True fail-fast means all prereqs are checked first, before a single
file is written. A partial install is worse than no install — the user now has hook scripts
pointing at a daemon that won't start.

**Suggested prereq additions to `install.sh` / `install_version.sh` Step 1:**

```bash
# Check git remote origin
git remote get-url origin &>/dev/null || _fail "No git remote 'origin' configured.
  The daemon requires a remote named 'origin'.
  Fix: git remote add origin <your-repo-url>"
```

---

## Bug 2 (Major): Installer silences daemon error output at Step 11

**Step**: Step 11 — "Starting daemon"

**What the installer printed:**

```
Step 11: Starting daemon
----------------------------------------
→ Restarting daemon...
[exits with code 1, no further output]
```

**What the daemon actually outputs** (only visible when running `cli status` manually afterwards):

```
ProjectContext: No git remote 'origin' configured
ERROR: Invalid configuration in /workspace/.claude/hooks-daemon.yaml:

FAIL FAST: Project at /workspace is not a git repository or has no remote origin.
All projects must be in git repositories.

Fix the configuration file and try again.
```

The daemon has a clear, actionable error message. The installer swallows it entirely.
The user is left with a silent exit code 1 and no idea what to fix.

**Fix**: In `install_version.sh` Step 11, capture and print the daemon's stderr/stdout
when the start command fails, so the actionable error is surfaced inline.

---

## Bug 3 (Minor): Version number mismatch — uv reports 2.21.1, `__version__` reports 2.4.0

During install, uv output showed:

```
+ claude-code-hooks-daemon==2.21.1 (from file:///workspace/.claude/hooks-daemon)
```

After install:

```
$ .claude/hooks-daemon/untracked/venv/bin/python -c \
    "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__version__)"
2.4.0
```

`pyproject.toml` version and `__version__` in source are out of sync.

**Severity**: Minor — cosmetic/diagnostic confusion.
**Fix**: Single source of truth for version (e.g. `importlib.metadata` or `hatch-vcs`).

---

## Steps to Reproduce Bugs 1 & 2

```bash
mkdir /tmp/test-project && cd /tmp/test-project
git init
mkdir .claude
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh \
  -o /tmp/hooks-daemon-install.sh
bash /tmp/hooks-daemon-install.sh
# Exits code 1 at Step 11 with no error message
```

**Workaround**: add a remote before installing:

```bash
git remote add origin https://github.com/placeholder/placeholder.git
```

---

## Bug 4 (Major): Status line shows wrong effort level — displays "high" while Claude runs at "medium"

**Symptom**: After fresh install, the status line shows 3 orange bars (▌▌▌ = high effort) but
Claude Code is actually running at medium effort.

**Root cause**: Two handlers interact badly:

1. `optimal_config_checker` (SessionStart, priority 52) writes `effortLevel: "high"` to
   `~/.claude/settings.json` via `_enforce_settings_sync()` if the key is missing
2. `model_context` (Status, priority 10) reads `effortLevel` from `~/.claude/settings.json`
   to decide how many bars to display

**The problem**: Writing to `~/.claude/settings.json` does NOT change Claude Code's runtime
effort level for the current session. Claude Code reads its config at startup. The
`optimal_config_checker` writes "high" to the file, the status line reads "high" from the
file and displays 3 bars, but Claude Code is still running at whatever effort it started
with (default: medium).

**The result**: User sees 3 bars (high), thinks Claude is working at full effort, but Claude
is actually running at medium. This is actively misleading — the user has no reason to
suspect the display is wrong.

**Workaround**: Manually run `/model` and select opus with high effort. This changes the
runtime setting AND the file.

**Suggested fixes**:

1. `model_context` should read effort from the Claude Code environment/runtime, not from the
   settings file (if such an API exists)
2. If no runtime API exists, `optimal_config_checker` should NOT write to settings.json
   silently — instead it should advise the user to run `/model` to set high effort
3. At minimum, if the handler writes to the file, it should display a clear warning:
   "Set effortLevel=high in settings.json — this will take effect on NEXT session, not now"

---

## Bug 5 (Medium): Installer does not offer plan workflow setup

**Symptom**: After install, the `CLAUDE/Plan/` directory referenced by `settings.json`
(`"plansDirectory": "./CLAUDE/Plan"`) exists but is empty. No `README.md`, no
`PlanWorkflow.md`, no templates. All 6 plan workflow handlers are disabled by default.

**Expected behaviour**: The installer should detect whether `CLAUDE/Plan/` exists and:

- If it exists with content: offer to enable plan workflow handlers (the project already
  uses plans)
- If it does not exist: offer to bootstrap a generic plan workflow with README.md,
  PlanWorkflow.md, and enable plan workflow handlers
- Either way: the user should be informed about the plan workflow and given a choice

**What actually happens**: The installer creates `CLAUDE/Plan/` (via `settings.json`
`plansDirectory`) but does nothing else. All plan handlers remain disabled. The user has no
idea that plan workflow exists or how to set it up.

**Impact**: The plan workflow is a major feature of the daemon. Users who install the daemon
never discover it unless they read the hooks-daemon's own CLAUDE/PlanWorkflow.md.

**Suggested fix**: Add a post-install step:

```
Step 12: Plan Workflow Setup (Optional)
----------------------------------------
The hooks daemon supports structured plan-based development.
Plans track work in CLAUDE/Plan/001-description/, CLAUDE/Plan/002-description/, etc.

Would you like to enable plan workflow? (Y/n)
→ Creating CLAUDE/Plan/README.md
→ Creating CLAUDE/PlanWorkflow.md
→ Enabling plan workflow handlers in hooks-daemon.yaml
```

---

## Bug 6 (Minor): Most handlers disabled by default — no guidance on which to enable

**Symptom**: Of 73 total handlers, many useful ones are disabled by default with only a
brief inline comment. The user has no guidance on which handlers are recommended for their
project type.

**Disabled handlers that most projects would benefit from**:

- `qa_suppression` — blocks lint/test suppression comments
- `tdd_enforcement` — enforces test-first development
- `plan_number_helper`, `validate_plan_number`, `plan_time_estimates`, `plan_workflow`,
  `plan_completion_advisor` — full plan workflow suite
- `markdown_organization` — enforces doc organisation
- `transcript_archiver` — saves conversation history
- `workflow_state_restoration` + `workflow_state_pre_compact` — state management
- `critical_thinking_advisory` — quality nudges
- `validate_instruction_content` — prevents junk in CLAUDE.md
- `lint_on_edit` — auto-lint after edits
- `task_completion_checker` — verifies task completion

**Suggested fix**: The installer (or a post-install wizard) should present handler
categories and let the user choose a profile:

- **Minimal**: Safety handlers only (current default)
- **Recommended**: Safety + code quality + plan workflow
- **Strict**: All handlers enabled

---

## Summary: Post-Install Actions Required

After working around Bugs 1-2 (adding `git remote origin` and restarting daemon), the
following manual steps were needed to get the daemon fully operational:

1. **Fix effort level** (Bug 4): Run `/model`, select opus with high effort
2. **Set up plan workflow** (Bug 5): Create `CLAUDE/Plan/README.md`,
   `CLAUDE/PlanWorkflow.md`, enable 6 plan workflow handlers in `hooks-daemon.yaml`
3. **Enable recommended handlers** (Bug 6): Manually edit `hooks-daemon.yaml` to enable
   ~15 additional handlers that should be on by default for most projects
4. **Set up status line** (worked automatically via `suggest_status_line` handler)

**Total post-install manual work**: ~30 minutes of configuration that should have been
handled by the installer or a post-install wizard.

---

## What deployed successfully (everything except a running daemon)

- `.claude/hooks/` — all 11 hook scripts, executable
- `.claude/settings.json` — hook registration
- `.claude/hooks-daemon.yaml` — full handler config
- `.claude/hooks-daemon.env`
- `.claude/init.sh`
- `.claude/.gitignore` + root `.gitignore` — daemon exclusion entries
- `.claude/commands/` and `.claude/skills/hooks-daemon/`
