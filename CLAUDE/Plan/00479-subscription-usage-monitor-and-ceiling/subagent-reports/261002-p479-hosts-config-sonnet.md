# Plan 00479 Tasks 3.1 and 3.2: hosts config and resolver

## Built

- `src/claude_code_hooks_daemon/config/models.py`: `UsageCeilingConfig`, `HostConfig`, and `Config.hosts: dict[str, HostConfig]` (extra="forbid" on both new models; `Config` itself stays extra="allow" like every other top-level section).
- `src/claude_code_hooks_daemon/utils/host_usage_ceiling.py`: `HostUsageCeiling` and `resolve_host_usage_ceiling`.
- Matching reuses `utils/cron_hosts.hostname_matches` (case-sensitive fnmatchcase); the effective hostname stays `utils/cron_hosts.effective_hostname`, which callers pass in.
- Docs: `docs/guides/CONFIGURATION.md` (new "Hosts" section), `.claude/hooks-daemon.yaml.example` (commented block), config-changes entry in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`, release note `212-...`.

## Rulings applied

- Lowest matching ceiling wins, per window.
- `max_used_percent` applies to both windows; `five_hour` and `seven_day` override it. At least one of the three is required; each must be a number with 0 < x \<= 100 (bool and strings rejected).

## Notes

- The main-checkout plan edit recording the two rulings was left alone (uncommitted in /workspace).
- `models.py` is flagged `too-broad` by the changed-tests mapper, so `llm_qa.py changed --allow-unmapped` was needed for that file only.
- No `persistent_crons` folding was done (open question 4).
