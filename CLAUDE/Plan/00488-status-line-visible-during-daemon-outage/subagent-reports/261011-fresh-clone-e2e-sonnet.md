# Fresh-clone e2e: Plan 00488 Task 3.1 and mechanical half of Task 4.1

Source under test: /workspace main at 737bb1690 (version 3.69.0), cloned locally. Host: Python 3.11.2, uv present, network available. All work under `/workspace/untracked/scratch/e2e-488/`; /workspace's own daemon, venv and tracked files were not touched. All three scratch daemons were stopped at the end and no process of mine remains.

## Verdict

| Mode                                              | Result                                                                                                                                                          |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (a) self-install, raw `git clone`                 | FAIL as literally posed: no recovery without a manual step (`scripts/bootstrap-self-install.sh`). Wrong "install" advice is given.                              |
| (a') self-install, env file present, venv missing | PASS with one gap: the self-heal builds the venv and starts the daemon, status line goes building -> loading -> normal, always exit 0.                          |
| (b) client project, install from local clone      | PASS: the installer builds the venv and starts the daemon synchronously (14 s).                                                                                 |
| (b') client, installed, venv removed              | PASS: building -> loading -> normal, exit 0, daemon up in 4 s.                                                                                                  |
| (b'') client, fresh clone of the project          | By design a manual `bash .claude/provision.sh` step (13 s); hooks say so and the status line exits 0. After it, the daemon runs, but in DEGRADED mode (gap G4). |

## Timeline: (a) self-install, raw fresh clone (log: self.log)

`git clone /workspace self`; no venv, no `.claude/hooks-daemon.env` (gitignored, per-checkout).

| t     | Probe         | rc  | Output                                                                                                                    |
| ----- | ------------- | --- | ------------------------------------------------------------------------------------------------------------------------- |
| 0.1 s | status-line   | 0   | `⚠️ DAEMON FAILED` (generic; stderr: "canonical library missing at .../.claude/hooks-daemon/scripts/lib/resolve_venv.sh") |
| 0.2 s | session-start | 0   | context "HOOKS DAEMON: Not installed ... use the hooks-daemon skill to install"                                           |
| all   | pre-tool-use  | 0   | benign and `git reset --hard` probes both answered with the same advisory: fails open, no deny                            |

Polled for 41 s: no change, no self-heal. init.sh looks for the daemon in `.claude/hooks-daemon/` because `hooks-daemon.env` is absent, so it never reaches the venv self-heal. Recovery needs `scripts/bootstrap-self-install.sh`, which builds the venv synchronously and then writes the env file.

## Timeline: (a') self-install, env file written by hand, no venv (logs: self2.log, self3.log, self4.log)

Env file content `HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"` (what the bootstrap writes). Three runs, venv deleted before each.

Run 4 (warm default uv cache, poll 0.5 s):

| t     | Probe         | rc  | Output                                                                      |
| ----- | ------------- | --- | --------------------------------------------------------------------------- |
| 0.2 s | status-line   | 0   | `⏳ HOOKS DAEMON VENV BUILDING - wait, no action needed` (starts the build) |
| 0.3 s | session-start | 0   | "clone present, venv missing for this project path"                         |
| 0.8 s | status-line   | 0   | `⏳ hooks daemon loading…`                                                  |
| 3.2 s | pre-tool-use  | 0   | waited 2.4 s for the daemon, then real answer (benign: advisory only)       |
| 3.3 s | pre-tool-use  | 0   | `git reset --hard` DENIED by R-GIT-RESET-HARD (daemon live)                 |
| 4.3 s | status-line   | 0   | normal line                                                                 |

Total 4.5 s to a running daemon, no manual step.

Run 3 (cold uv cache via `UV_CACHE_DIR`, poll 2 s): building at 0.2 s; **at 0.5 s status-line printed `⚠️ DAEMON FAILED` (rc 0) and both PreToolUse probes returned `permissionDecision: deny` "could not connect at all - denied for safety"** (stderr "Cannot import claude_code_hooks_daemon. Venv may be broken"); loading at 3.1 s; normal at 8.1 s. Run 2 (warm cache) showed the same transient (0.4 s to ~0.7 s), normal at 9.3 s. Run 4 did not hit it (race).

Build time: 4.5 to 9.4 s on this host (small wheels, fast network). The 2-minute window in the field report was not reproduced; the full `--all-extras` build here is quick.

## Timeline: (b) client project (log: client-install.log, client1.log)

Setup: scratch git project with `origin`, `git clone /workspace .claude/hooks-daemon` (main HEAD, not a tag), then `scripts/install_version.sh <project> <daemon>` (the LLM-INSTALL.md manual path, step 3).

- Install: rc 0, 14 s, venv built, daemon `RUNNING`, forwarders/settings/config written. No venv existed before the installer, none was needed at hook time.
- (b') daemon stopped and `untracked/venv-*` deleted, then driven:

| t     | Probe         | rc  | Output                                                        |
| ----- | ------------- | --- | ------------------------------------------------------------- |
| 0.2 s | status-line   | 0   | `⏳ HOOKS DAEMON VENV BUILDING - wait, no action needed`      |
| 0.3 s | session-start | 0   | "clone present, venv missing for this project path"           |
| 1.0 s | status-line   | 0   | `⏳ hooks daemon loading…`                                    |
| 3.1 s | pre-tool-use  | 0   | `{}` (allow) after 2.2 s wait; `git reset --hard` then DENIED |
| 3.8 s | status-line   | 0   | normal line                                                   |

Total 4.0 s. No "DAEMON FAILED" transient this run.

## Timeline: (b'') fresh clone of the client project (logs: client2.log, provision.log, client3.log)

`git clone` of the committed client project: tracked `.claude/` assets only, no `.claude/hooks-daemon/`.

- status-line: `⚠️ HOOKS DAEMON NOT PROVISIONED - run: bash .claude/provision.sh`, rc 0 (the stderr shows a resolve_venv error line, harmless).
- session-start and pre-tool-use: "NEEDS PROVISIONING" advisory, fail open (no deny; `git reset --hard` probe not denied while unprovisioned; default `unprovisioned_mode`).
- No self-heal; waited 20 s. `bash .claude/provision.sh`: rc 0, 13 s, "PROVISIONED ... daemon running", no tracked file changed.
- After provisioning the status line and hooks report DEGRADED MODE (see G4).

## Gaps

- **G1 (manual step, self-install).** A raw clone of the repository cannot self-heal: `.claude/hooks-daemon.env` is gitignored, so init.sh looks in `.claude/hooks-daemon/`. Status line shows the generic `⚠️ DAEMON FAILED` (rc 0, visible), SessionStart says "Not installed ... use the hooks-daemon skill to install", which is wrong advice in self-install mode (installers abort there; the right step is `scripts/bootstrap-self-install.sh`). The status line has no text naming this state. Task 3.1's "no manual step" bar is not met for a raw clone of this repo.
- **G2 (wrong text and fail-closed during the build).** A sub-second to ~1 s window right after the build starts (partial venv: interpreter exists, package not importable) is classified as a broken venv: status line `⚠️ DAEMON FAILED` instead of "venv building" (rc is 0, so it is visible, but it misdescribes the state), and PreToolUse DENIES every tool call, benign ones included, "could not connect at all - denied for safety". Seen in 2 of 3 self-install runs, 0 of 1 client run. Contrasts with the later "loading" window where PreToolUse waits up to about 2.5 s and then answers. This is relevant to Task 3.2 (build-window policy): the build window is not uniformly fail-open.
- **G3 (client, not automatic).** A fresh clone of a client project is not self-healing; it needs `bash .claude/provision.sh` (documented, by design, Plan 00477). Status line text and exit code (0) are right; PreToolUse fails open until then.
- **G4 (version skew in this test only).** The client config was generated from main HEAD (`expected_version: "3.69.0"`, includes `write_protected_paths`), but `provision.sh` fetched the released tag v3.69.0, which lacks that handler: "DEGRADED MODE - Unknown handler 'write_protected_paths'". Because the unreleased tree reports the same version as the tag, a main-installed client is degraded after provisioning. Not a defect for tag installs; do not read it as a 488 regression.
- **Not exercised:** a build long enough to watch the status line sit on "venv building" for minutes (builds took 4 to 9 s); a real Claude Code process rendering the bar (Task 4.1 live half); container-built-venv mismatch. No hang or timeout occurred anywhere; every status-line call returned rc 0 in under 0.6 s.

## Commands to re-run

Scripts live in `/workspace/untracked/scratch/e2e-488/`: `drive.sh` (timeline driver), `client-setup.sh`, `client-fresh-setup.sh`. `drive.sh <project> <label> <max_s>` pipes minimal Status, SessionStart and PreToolUse JSON (benign `echo hello`, and `git reset --hard HEAD~1` as the deny probe, never executed) to `<project>/.claude/hooks/{status-line,session-start,pre-tool-use}` with `CLAUDE_PROJECT_DIR` set; env `POLL` (seconds), `OUTW` (output width).

```bash
B=/workspace/untracked/scratch/e2e-488
# (a) raw self-install clone
git clone -q /workspace $B/self
timeout 120 $B/drive.sh $B/self self-raw 40
# (a') add the env file, then drive (delete venvs between runs: rm -rf $B/self/untracked/venv-*)
printf 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"\n' > $B/self/.claude/hooks-daemon.env
POLL=0.5 OUTW=160 timeout 900 $B/drive.sh $B/self self-heal 600
$B/self/bin/hooks-daemon stop
# (b) client install, then venv-removed drive
bash $B/client-setup.sh
$B/client/.claude/hooks-daemon/bin/hooks-daemon stop
rm -rf $B/client/.claude/hooks-daemon/untracked/venv-*
POLL=0.5 timeout 900 $B/drive.sh $B/client client-heal 600
# (b'') fresh clone of the client project, then provision
bash $B/client-fresh-setup.sh
timeout 120 $B/drive.sh $B/client-fresh unprovisioned 20
(cd $B/client-fresh && CLAUDE_PROJECT_DIR=$B/client-fresh timeout 300 bash .claude/provision.sh)
# cleanup
$B/client-fresh/.claude/hooks-daemon/bin/hooks-daemon stop; $B/client/.claude/hooks-daemon/bin/hooks-daemon stop
```

Cold uv cache variant: prefix the drive with `UV_CACHE_DIR=$B/uvcache`. Raw logs: `self.log`, `self2.log`, `self3.log`, `self4.log`, `client1.log`, `client2.log`, `client3.log`, `client-install.log`, `provision.log` in the same directory.
