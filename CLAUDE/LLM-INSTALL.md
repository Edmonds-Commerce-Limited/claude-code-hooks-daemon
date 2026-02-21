# Claude Code Hooks Daemon - LLM Installation Guide

## CRITICAL REQUIREMENTS - READ FIRST

**BEFORE PROCEEDING:**

1. **CHECK IF ALREADY INSTALLED**: Run the pre-installation check below. If `.claude/hooks-daemon/` exists, use UPDATE guide instead of installing. Reinstalling over existing installation can lose config customizations.

2. **CONTEXT WINDOW CHECK**: You MUST have at least **100,000 tokens** remaining in your context window. If below 100k, STOP and ask user to start fresh session. Installation failures due to compaction cannot be recovered.

3. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch tool, you MUST use a prompt that DISABLES summarization. Fetch with: `"Return complete document verbatim without summarization, truncation, or modification"`. Missing instructions cause installation failure.

4. **GIT CLEAN STATE**: Working directory MUST be clean (no uncommitted changes). Run `git status` - if not clean, commit/push ALL changes first. Rollback impossible without clean git state.

5. **PYTHON 3.11+**: Verify with `python3 --version`. Installation fails on older versions.

6. **SESSION RESTART REQUIRED**: After installation completes, user MUST restart Claude session. Hooks won't activate until Claude reloads configuration. LLM MUST verify hooks work after restart.

7. **GITIGNORE**: The installer automatically creates `.gitignore` files (root and `.claude/.gitignore`). If auto-creation fails, follow the manual instructions displayed by the installer.

---

## Architecture Overview

The installation system uses a **two-layer architecture**:

- **Layer 1** (`install.sh`): Minimal curl-fetched script (~100 lines). Validates prerequisites, clones the repository, then delegates to Layer 2 via `exec`.
- **Layer 2** (`scripts/install_version.sh`): Version-specific orchestrator that sources a shared modular library (`scripts/install/*.sh`) for all operations.

This design means Layer 1 is stable across versions (safe to curl from GitHub), while Layer 2 evolves with the codebase and always matches the installed version.

---

## Troubleshooting & Bug Reports

**If installation fails or hooks don't work:**

See [BUG_REPORTING.md](../BUG_REPORTING.md) for comprehensive debugging guide.

**Quick debug in client projects:**
```bash
# Run from your project root
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

This generates a complete diagnostic report for GitHub issues.

---

## Pre-Installation Check: Is Daemon Already Installed?

**IMPORTANT: Check if daemon is already installed before proceeding!**

Running the install process on an existing installation can cause issues. If already installed, use the UPDATE guide instead.

### Check for Existing Installation

```bash
# From your project root
if [ -d ".claude/hooks-daemon" ]; then
  echo "DAEMON ALREADY INSTALLED"
  echo ""
  echo "Found existing installation at .claude/hooks-daemon/"
  echo ""
  echo "To UPDATE the daemon (recommended):"
  echo "  Read: https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md"
  echo ""
  echo "To REINSTALL from scratch (will lose config customizations):"
  echo "  1. Backup: cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup"
  echo "  2. Remove: rm -rf .claude/hooks-daemon"
  echo "  3. Run install steps below"
  echo ""
  exit 1
else
  echo "No existing installation found - safe to proceed with installation"
fi
```

**If daemon is already installed:**
- **DO NOT continue with installation steps below**
- Use the UPDATE guide: [CLAUDE/LLM-UPDATE.md](https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md)
- Reinstalling will lose your config customizations

**If no daemon found:**
- Continue with installation steps below

---

## Quick Install (Recommended)

The installer handles everything via the two-layer architecture:

```bash
# From your project root (must have .claude/ and .git/)

# Step 1: Download the installer script
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh

# Step 2: Inspect it (good security practice)
cat /tmp/hooks-daemon-install.sh

# Step 3: Run it
bash /tmp/hooks-daemon-install.sh
```

> **Note**: We intentionally avoid `curl | bash` because the daemon itself blocks that
> pattern as a security risk. Practice what we preach.

This will:
1. Validate prerequisites (git required)
2. Clone the daemon repository to `.claude/hooks-daemon/`
3. Delegate to the version-specific Layer 2 installer which:
   - Checks for self-install mode (aborts if detected)
   - Verifies Python 3.11+ and installs uv if needed
   - Creates isolated venv at `.claude/hooks-daemon/untracked/venv/`
   - Deploys hook forwarder scripts to `.claude/hooks/`
   - Generates `.claude/settings.json` for hook registration
   - Creates `.claude/hooks-daemon.env` environment file
   - Generates default `.claude/hooks-daemon.yaml` config
   - Sets up all `.gitignore` files
   - Deploys slash commands to `.claude/commands/`
   - Starts the daemon and verifies it is running

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DAEMON_BRANCH` | `main` | Git branch or tag to install |
| `FORCE` | `false` | Set to `true` to reinstall over existing |

```bash
# Install specific version
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh
DAEMON_BRANCH=v2.5.0 bash /tmp/hooks-daemon-install.sh

# Force reinstall
FORCE=true bash /tmp/hooks-daemon-install.sh
```

---

## Manual Install (6 Steps)

If you prefer manual control over each step:

### 1. Verify Prerequisites

```bash
# Must show clean - if not, commit everything first
git status --short

# Must be 3.11+
python3 --version

# Optional: Commit existing .claude/ config as safety checkpoint
git add .claude/ && git commit -m "Save hooks before daemon install" && git push || true
```

### 2. Clone & Setup Venv

```bash
mkdir -p .claude && cd .claude

# Clone and checkout latest stable release tag
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon
git fetch --tags
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
git checkout "$LATEST_TAG"
echo "Using version: $LATEST_TAG"

# Create isolated venv (survives container restarts)
python3 -m venv untracked/venv
untracked/venv/bin/pip install -e .

# Verify
untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"
```

### 3. Run Installer

```bash
# The installer auto-detects project root by searching upward for .claude/
# Creates .claude/hooks/, settings.json, hooks-daemon.yaml
# DISPLAYS (but does not create) required .claude/.gitignore content
untracked/venv/bin/python install.py

# For explicit control (optional):
# untracked/venv/bin/python install.py --project-root /workspace

cd ../..
```

**Files created:**
- `.claude/init.sh` - Daemon lifecycle functions
- `.claude/hooks/*` - Forwarder scripts
- `.claude/settings.json` - Hook registration
- `.claude/hooks-daemon.yaml` - Handler config (with container auto-detection)

**Container Auto-Detection**:
- During config generation, the installer detects container environments (Docker, Podman, YOLO mode)
- If container detected, automatically enables `enforce_single_daemon_process: true`
- In containers: Ensures only ONE daemon process runs system-wide (kills duplicates)
- Outside containers: Only cleans stale PID files (safe for multi-project setups)
- No manual configuration needed - works automatically based on environment

**Note**: The installer automatically creates `.claude/.gitignore` with the correct entries. If auto-creation fails, it will display manual instructions.

### 4. Commit & Restart

```bash
# Verify .gitignore was auto-created
ls -la .claude/.gitignore

# If missing, copy from template:
# cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore

# Commit (with .gitignore in place to exclude generated files)
git add .claude/
git commit -m "Install Claude Code Hooks Daemon" && git push
```

**CRITICAL**:
1. Verify `.claude/.gitignore` exists before `git add` or you'll commit hooks-daemon/
2. Tell user to **restart Claude session** (exit and re-enter). Hooks won't activate until Claude reloads `.claude/settings.json`.
3. Do NOT proceed to step 5 until session restarts.

### 5. Verify Hooks Active (After Restart)

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Check daemon auto-started (lazy startup on first hook call)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Test destructive git is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test sed is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "sed -i s/foo/bar/ file.txt"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test normal commands pass through
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {} (empty = allow)
```

**If all tests pass**: Hooks active.

**If tests fail**: Check troubleshooting section below.

### Installation Success Criteria

A successful installation meets ALL of these conditions:

1. **Daemon running**: `$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status` shows `RUNNING`
2. **Hooks deployed**: `.claude/hooks/pre-tool-use` and other hook scripts exist and are executable
3. **Blocking works**: `echo '{"tool_name":"Bash","tool_input":{"command":"git reset --hard"}}' | .claude/hooks/pre-tool-use` returns a `deny` decision
4. **Safe commands pass**: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | .claude/hooks/pre-tool-use` returns `{}` (allow)
5. **No DEGRADED MODE**: `$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs` shows no "DEGRADED MODE" warnings
6. **Git clean**: `.claude/hooks-daemon/` is excluded via `.gitignore`, not tracked by git

If any of these fail, see Troubleshooting section below.

---

### 6. Configure Handlers (Optional)

Edit `.claude/hooks-daemon.yaml`:

```yaml
daemon:
  idle_timeout_seconds: 600  # 10min auto-shutdown
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}   # Blocks git reset --hard, clean -f
    sed_blocker: {enabled: true, priority: 10}       # Blocks sed (use Edit tool)
    absolute_path: {enabled: true, priority: 12}     # Enforces absolute paths
    tdd_enforcement: {enabled: false, priority: 35}  # Enable for TDD workflow
    british_english: {enabled: false, priority: 60}  # Enable for UK spelling
```

Restart daemon after config changes:
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

**Note**: Settings.json changes require Claude session restart, config.yaml changes only need daemon restart.

---

## Post-Installation: Handler Status Report

After installation and configuration, generate a comprehensive report showing all handlers and their status:

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py
```

This displays a detailed table with:
- **All available handlers** organized by event type (PreToolUse, PostToolUse, etc.)
- **Enabled/Disabled status** for each handler
- **Priority and terminal settings**
- **Handler tags** (language, function, specificity)
- **Handler-specific configuration options** (if enabled)
- **Summary statistics** (total handlers, enabled count, disabled count)
- **Tag filtering info** (if using enable_tags/disable_tags)

**Save for reference:**
```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py > /tmp/handler-status.txt
cat /tmp/handler-status.txt
```

---

## Post-Installation: Update Project CLAUDE.md

Add a `### Hooks Daemon` section to the **project's root `CLAUDE.md`** so future agents working in this project know how to manage the daemon.

### Check if Section Exists

```bash
grep -n "### Hooks Daemon" CLAUDE.md 2>/dev/null || echo "MISSING - add section"
```

### Add or Update the Section

If missing (or outdated), append the following to the **bottom** of the project's root `CLAUDE.md`:

```markdown
### Hooks Daemon

This project uses [claude-code-hooks-daemon](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon) for automated code quality and workflow enforcement.

**After editing `.claude/hooks-daemon.yaml`** — restart the daemon:
```bash
/hooks-daemon restart
```

**Check status**: `/hooks-daemon health`

**Key files**:
- `.claude/hooks-daemon.yaml` — handler configuration (enable/disable handlers)
- `.claude/project-handlers/` — project-specific custom handlers (if any)

**Documentation**: `.claude/hooks-daemon/CLAUDE/LLM-INSTALL.md`
```

### Rules

- Keep the section terse — 10 lines maximum
- Do not duplicate if a `### Hooks Daemon` section already exists; update it in place instead
- This section is for **project agents**, not end users — focus on operational commands

---

## Post-Installation: Planning Workflow Adoption (Optional)

The daemon includes a comprehensive planning workflow system with numbered plan directories and enforcement handlers. Check if you want to adopt this approach.

### Check for Existing Planning Documentation

```bash
# Look for existing planning docs in common locations
find . -maxdepth 3 \( \
  -name "PLANNING.md" -o \
  -name "PlanWorkflow.md" -o \
  -name "Planning.md" -o \
  -path "*/docs/planning/*" -o \
  -path "*/CLAUDE/planning*" -o \
  -path "*/Plan/*" \
) 2>/dev/null
```

### Compare with Hooks Daemon Approach

The daemon uses a structured planning system:

**View the daemon's planning workflow:**
```bash
cat .claude/hooks-daemon/CLAUDE/PlanWorkflow.md | head -100
```

**Key features:**
- Numbered plan directories (CLAUDE/Plan/001-description/, 002-description/)
- Standardized PLAN.md template with tasks, goals, success criteria
- Task status system
- TDD integration and QA enforcement
- Planning-specific handlers for enforcement

**Enforcement handlers available:**
- `plan-workflow-guidance` - Guides through planning steps
- `validate-plan-number` - Validates plan numbering consistency
- `block-plan-time-estimates` - Prevents time estimates in plans
- `enforce-markdown-organization` - Enforces markdown organization rules

### If User Chooses to Adopt

**1. Copy planning workflow documentation:**
```bash
mkdir -p CLAUDE/Plan
cp .claude/hooks-daemon/CLAUDE/PlanWorkflow.md CLAUDE/PlanWorkflow.md

if [ ! -f "CLAUDE/Plan/README.md" ]; then
  echo "# Plans Index

## Active Plans
- None

## Completed Plans
- None
" > CLAUDE/Plan/README.md
fi
```

**2. Enable planning enforcement handlers** in `.claude/hooks-daemon.yaml`:
```yaml
handlers:
  pre_tool_use:
    plan-workflow-guidance: {enabled: true, priority: 45}
    validate-plan-number: {enabled: true, priority: 30}
    block-plan-time-estimates: {enabled: true, priority: 40}
    enforce-markdown-organization: {enabled: false, priority: 35}  # EC-specific
```

**3. Restart daemon:**
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

### If User Chooses to Skip

No action needed. The planning handlers will remain disabled.

---

## Custom Handler Migration

If you had custom hooks before install (backed up to `.claude/hooks.bak.TIMESTAMP/`):

**1. Find backup:**
```bash
ls -d .claude/hooks.bak.* 2>/dev/null | tail -1
```

**2. Create handler file:**
```bash
mkdir -p .claude/hooks/handlers/pre_tool_use
# Create .claude/hooks/handlers/pre_tool_use/my_handler.py
```

**3. Handler template:**
```python
"""MyHandler - brief description."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks-daemon/src"))

from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        command = hook_input.get("tool_input", {}).get("command", "")
        return "npm" in command

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Use project script instead")
```

**4. Register in config:**
```yaml
handlers:
  pre_tool_use:
    my_handler: {enabled: true, priority: 50}
```

**5. Restart:**
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

---

## Troubleshooting Common Issues

**For comprehensive troubleshooting, see [BUG_REPORTING.md](../BUG_REPORTING.md)**

### Quick Diagnostics

**Generate full debug report:**
```bash
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

### Common Quick Fixes

**Daemon won't start:**
```bash
# Check Python version (must be 3.11+)
python3 --version

# Verify installation
.claude/hooks-daemon/untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"

# Check logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
```

**Handlers not blocking:**
```bash
# Test hook manually
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}' | .claude/hooks/pre-tool-use

# Check handler config
grep -A 1 "destructive_git:" .claude/hooks-daemon.yaml
```

**Hooks not working after install:**
1. **Restart Claude session** (required for settings.json changes)
2. Run debug script to see what's wrong
3. Check [BUG_REPORTING.md](../BUG_REPORTING.md)

**Layer 2 installer not found (legacy fallback):**
If you see "Layer 2 installer not found" during install, you are installing an older version that predates the modular architecture. The legacy fallback (uv sync + install.py) will handle the installation. This is expected for tags before the two-layer architecture was introduced.

### Rollback to Previous Hooks

**Option 1 - Git restore (if you committed before install):**
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
git restore .claude/
rm -rf .claude/hooks-daemon/
```

**Option 2 - Backup directory (if no git commit):**
```bash
BACKUP_DIR=$(ls -d .claude/hooks.bak.* 2>/dev/null | tail -1)
if [ -z "$BACKUP_DIR" ]; then
    echo "No backup - rollback impossible without git commit"
    exit 1
fi

.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
rm -rf .claude/hooks
mv "$BACKUP_DIR" .claude/hooks
```

---

## CLI Reference

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

---

## Handler Priority Ranges

- **5**: Test/debug handlers
- **10-20**: Safety (destructive git, sed blocker)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English, formatting)

Lower priority = runs first. Terminal handlers stop dispatch chain.

---

## Directory Structure After Install

```
project/
├── .claude/
│   ├── .gitignore              # AUTO-CREATED by installer
│   ├── init.sh                 # COMMIT - Daemon lifecycle
│   ├── hooks-daemon.yaml       # COMMIT - Handler config
│   ├── hooks-daemon.env        # COMMIT - Environment variables
│   ├── settings.json           # COMMIT - Hook registration
│   ├── hooks/                  # COMMIT - Forwarder scripts
│   │   ├── pre-tool-use
│   │   ├── post-tool-use
│   │   └── handlers/           # COMMIT - Custom handlers
│   ├── commands/               # COMMIT - Slash commands
│   └── hooks-daemon/           # EXCLUDED via .gitignore
│       ├── src/                # Daemon source code
│       ├── scripts/
│       │   ├── install/        # Shared modular library (14 modules)
│       │   ├── install_version.sh  # Layer 2 install orchestrator
│       │   └── upgrade_version.sh  # Layer 2 upgrade orchestrator
│       └── untracked/
│           └── venv/           # Isolated Python environment
```

**Git Integration:**
- Installer automatically creates `.claude/.gitignore` with daemon exclusion entries
- Root `.gitignore` also updated automatically with `.claude/hooks-daemon/` entry
- If auto-creation fails, manual instructions are displayed

---

## Feedback & Issue Reporting

**IMPORTANT**: During the installation process, keep detailed notes of everything that happens. Create a feedback file that the user can optionally share with the project maintainers to improve the install experience.

### Create Feedback File

After installation completes (whether successful or not), create a detailed feedback file at the project root:

```bash
cat > install-feedback-$(date +%Y%m%d).md << 'EOF'
# Installation Feedback Report

## Environment
- **Date**: [today's date]
- **Target Version**: [version installed]
- **OS**: [operating system and version, e.g. uname -a output]
- **Python Version**: [python3 --version output]
- **Default Python Path**: [which python3 output]
- **Project Path**: [absolute path to project root]
- **Project Path Length**: [character count]

## Installation Method
- [ ] Automated (install.sh via curl)
- [ ] Manual (step-by-step)

## Results
- **Overall**: SUCCESS / PARTIAL / FAILED
- **Duration**: [approximate time taken]
- **Daemon Status**: RUNNING / FAILED / NOT STARTED

## Step-by-Step Log
[Document each step: what command was run, what output was received, any errors or warnings]

1. **Pre-flight checks**: ...
2. **Prerequisites (git, python, uv)**: ...
3. **Repository clone**: ...
4. **Venv creation**: ...
5. **Config generation**: ...
6. **Hook deployment**: ...
7. **Daemon start**: ...
8. **Verification**: ...
9. **Session restart**: ...

## Issues Encountered
[List any problems, workarounds, or unexpected behavior]

1. **Issue**: [description]
   **Severity**: Critical / Major / Minor / Cosmetic
   **Workaround**: [what you did to get past it]
   **Suggestion**: [how it could be improved]

## Documentation Gaps
[Note any missing, unclear, or incorrect documentation in LLM-INSTALL.md]

1. [description of gap or inconsistency]

## Suggestions
[Any improvements to the installation process]

1. [suggestion]

## Warnings & Anomalies
[Any warnings logged, unexpected behavior, or things that seemed wrong but didn't break anything]
EOF
```

### What to Document During Installation

Actively note throughout the process:
- **Every command** you run and its output (especially errors/warnings)
- **Every decision point** where you had to choose between options
- **Documentation inconsistencies** where docs said one thing but reality was different
- **Missing prerequisites** that weren't mentioned in docs
- **Confusing error messages** that didn't help diagnose the issue
- **Workarounds** applied that shouldn't be necessary
- **Time spent** on each step (helps identify bottlenecks)
- **Path/permission issues** especially on different OS configurations
- **Python version issues** (system python too old, alternative interpreters found)

### Sharing Feedback

The feedback file can be shared with project maintainers to improve the install process:

1. Open an issue at the project's GitHub repository
2. Attach or paste the feedback file content
3. Maintainers use this real-world data to fix installation issues

**Every piece of feedback makes the next installation smoother for everyone.**

---

## Bug Reports

Include in issue:
```bash
# Version
.claude/hooks-daemon/untracked/venv/bin/python -c "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__version__)"

# Python
python3 --version

# OS
uname -a

# Logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs > daemon-logs.txt

# Config (sanitize sensitive data)
cat .claude/hooks-daemon.yaml
```

**Submit:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/new

---

**Installation Date:** `date +%Y-%m-%d`
