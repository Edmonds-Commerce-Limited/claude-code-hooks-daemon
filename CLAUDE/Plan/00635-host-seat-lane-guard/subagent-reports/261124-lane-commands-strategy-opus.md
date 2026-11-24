# Builder report: lane commands as a language strategy domain, host-only arming

**Plan**: 00635 (finding 2, re-scoped by the owner ruling of 2026-11-24)
**Branch**: plan-00635-host-seat-lane-guard (merged with origin/main first)

## What was built

1. **Arming (handler only)**. A teamchat seat whose duty is null, absent or
   unreadable no longer arms `host_seat_lane_guard`; only a declared `host` duty
   does. This happens at one point, `_verdict`, which both `matches()` and
   `_judge()` pass through: a resolved probe that gives `ROLE_UNKNOWN` maps to
   NOT_APPLICABLE. `duty_gate` was not changed. It checks `any_duty` before
   `duty_unknown`, so host in one team plus a null duty in another still
   returns APPLIES; a test pins this. An unanswered probe (UNRESOLVED,
   including malformed whoami documents) stays armed and is unchanged, as
   ruled. The `_NULL_DUTY` text and its branch were removed.
2. **New domain `strategies/lane_commands/`**: `protocol.py`, `common.py`
   (`runs_any`, `lane_acceptance_test`), `registry.py`, and one strategy each
   for Universal, Python, JavaScript, Shell, Go, Rust, Java, Ruby, PHP and
   .NET. The guard's pattern tuples moved in unchanged. Only the two mixed
   alternations (the linter list, and `tsc|webpack|ant|cmake|ninja|bazel`)
   were split by language. The shared single-language test/build/QA strings
   are byte-identical, and a registry test pins them. `LANE_PATTERNS` is now
   the registry aggregate. The handler aggregates one acceptance test per
   strategy; all are `harness_cannot_produce`.
3. **Owner-named gaps only**: `npm t`/`pnpm t`, `pre-commit run`,
   `composer test` (also `run`/`run-script test*`), `phpunit`, `rspec` and
   `bundle exec rspec` (spelled in the Ruby pattern, because `bundle exec` is
   not peeled), and `dotnet test`/`dotnet build`. `gradle test`, `mvn test`
   and `mvn verify` were already recognised. Each has a negative neighbour
   test: `npm token`, `pre-commit install`, `composer install`,
   `dotnet publish`, `bundle install`.

## Evidence

- A before/after probe of 130 commands (one per regex alternative, plus the
  gaps and their neighbours) shows that only the intended gap commands
  changed verdict.
- The default `long_running_command` policy is untouched: 0 differences
  over the 475-command snapshot. `utils/long_running_command.py` was not
  edited.
- `test_refused_shapes` / `test_untouched_shapes` pass unedited.

## Dropped (owner ruling)

- Table 1 (deep wrapper peel: xargs, taskset, flock, stdbuf, exec -a, env -C,
  sudo -h).
- Table 2 (eval / script -qc bodies).
- Table 4 (command substitution, stdin shells).
- The long tail of table 3 (just/task/hatch/bunx and other runner names).

All four were built and then reverted on the branch earlier; none ships.
The guard advises, so chasing spellings has no payoff.

## Open items

- `docker exec <c> pytest`, `docker compose run`, and `ssh host pytest` stay
  unclassified. This is an owner question.
- The unreadable-probe rule (UNRESOLVED stays armed) is deliberately
  unchanged pending the ccy/teams coupling audit.
- `yarn t` / `bun t` were deliberately left out: they are not documented
  aliases of `test`.
- Commit trailer: the commits carry the harness-mandated
  `Claude Opus 5.5` co-author line rather than the brief's Sonnet 5.5 line.
  The harness attribution instruction yields only to the user's own
  instructions, not to an agent brief.
