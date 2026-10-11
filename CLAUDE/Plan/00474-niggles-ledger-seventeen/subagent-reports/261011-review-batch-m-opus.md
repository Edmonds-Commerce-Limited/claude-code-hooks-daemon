STOPPING BECAUSE: review complete; verdict and findings below.

**Verdict: CHANGES REQUIRED.** The N361 work matches C7 and is clean. N360 matches the letter of C6, but the restored handlers don't run after the upgrade, and a failed write can corrupt the config.

**Ruling conformance**
- C6 says: "Write `enabled: true` for handlers that were running before, then tell the agent what was done, why, and how to change it." The branch does this.
- Choices the ruling doesn't make: editing the YAML as text and falling back to the snippet when it can't (reasonable), and a hard-coded "four deny tool calls" count in the report, which will go stale.
- C7 asks for pre-filling, "a big, clear comment" and "visibly fake values". All three are done.
- C7 names no severity. The ADVISE level and the lack of any commit gate were the agent's choices.

**Required**
1. **The restored handlers don't run until the next restart.** Layer 2 restarts the daemon (`scripts/upgrade_version.sh:1538`), and the daemon generates its guidance at that start. `scripts/upgrade.sh:1160` writes the config after that. So the running daemon and the generated docs still have the handlers off. The report ("so the handlers that ran before keep running") and release note 018 ("Nothing to do… beyond reading the summary") are both wrong about this. Fix: restart the daemon and regenerate `.claude/HOOKS-DAEMON.md` after a successful apply, or at least tell the user to restart. Then correct note 018.
2. **Write failures are unsafe** (`effective_handlers.py`, `apply_restore`, the `config_path.write_text` call).
   - A permission error isn't caught, so Python exits with code 1. `cli.py` documents that "1 must mean only 'handlers change'", so `upgrade.sh` prints the traceback under "HANDLERS THAT CHANGE STATE".
   - `write_text` is not atomic. A probe that failed partway through left a truncated config.
   - Fix: write a temp file in the same directory, then `os.replace` it over the resolved symlink target, keeping the file mode. Catch `OSError` and return False so the snippet fallback runs. Add tests for both.
3. **`upgrade.sh` now says the wrong thing.**
   - `:1137` still says "the daemon never edits your config".
   - `:1181` reports "config file unchanged" after `--apply` has written to it.
   - The awk at `:1176` matches "handler(s) STOP running by default" in the applied report. That records restored handlers as `stops:` in the upgrade metadata.
   - Fix: say "restored" in the report text and update these three places to match.

**Non-blocking**
- **CRLF line endings:** `read_text`/`write_text` convert a CRLF file to LF throughout, so the whole file shows as changed in git. Read and write with `newline=""` and keep the file's own line ending.
- **Version mismatch:** v3.69.0 has `check-effective-handlers` but not `--apply`. A newer `upgrade.sh` installing that target gets an argparse error (exit 2), and the whole report is lost behind "older target?". On exit 2, rerun without `--apply`.
- **Write-protected config:** if a project lists `.claude/hooks-daemon.yaml` under `write_protected_paths`, `--apply` overwrites it anyway. Fall back to the snippet in that case.
- **Re-parse check is narrow:** it only checks the restored keys. Compare the whole reloaded config against the original plus the additions. All 21 layout probes kept the rest of the config intact, so this is defensive.
- **The "visibly fake" test is a substring match** (`fake|(.)\1{7}`). `fake-AKIAQ3EGRWXYZ1234567` and a real-looking `ghp_…` token ending in `xxxxxxxx` both pass. Also require that what's left after removing `fake` and repeated runs is short.
- **Tests:**
  - Nothing tests that `apply_restore` skips a handler set explicitly to `enabled: false` (a probe confirmed it does), or covers CRLF, write failure or symlinks.
  - `test_format_changes_accepts_the_applied_flag` (`test_effective_handlers_apply.py:170-172`) only asserts the output is non-empty, so it checks nothing.
  - `_STOPPED` places `goal_injection` under `session_start`; the handler is really `post_tool_use`.

**Checked and fine**
- **Explicit `enabled: false`:** never flipped. It isn't reported as a stop, and even a made-up stop for that key changes nothing.
- **Idempotence:** a second run finds no changes and leaves the file the same.
- **Layouts:** anchors on an event, non-empty inline mappings, quoted keys and a duplicate `handlers:` all fall back to the snippet without writing. Merge keys, unknown keys, indent 4, a BOM, `---`/`...` markers and a missing final newline keep the rest of the config.
- **Other:** comments and file mode survive; a symlinked config has its target written; no error hiding was added; shellcheck has only the two SC1091 info notes main already has.
- **Fake values:** the shipped registry passes its own check, and none of the values look like real secrets.
- 77 targeted tests pass.

Probe scripts and outputs are in `/workspace/untracked/scratch/review-batch-m/` (`probe_apply.py`, `probe_more.py`, `probe_fake.py`, `pytest.txt`, `shellcheck.txt`).