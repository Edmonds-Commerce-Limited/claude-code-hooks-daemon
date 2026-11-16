# Park-carried restriction tests (Plan 00594)

The rule (`branch_inventory.is_park_residue`) already requires every commit in
`target..tip` to be an empty park commit, with at least one park. No rule change was needed.

Added `TestParkCarriedIsOnlyParkCommits` to `tests/unit/core/test_branch_park_carried.py`:

1. Remote-only park over real work stays PARKED; counted by the sweep and the creation guard (refuses at cap 1).
2. Non-empty commit above a park commit, remote-only: not park-carried, still counted.
3. Empty commit without a Parked-\* trailer over merged work: not park-carried.
4. Park over merged work plus a later non-empty commit: not park-carried.
5. Guard parked pool equals sweep parked pool on a mixed fixture (six carried, remote-only and local real parks).

Mutation check: dropping the `len(commits) == len(parks)` clause fails 4 of the 5 tests (restored).
The 37 tests in the file pass; ruff and black are clean; mypy shows only pre-existing conftest errors.
