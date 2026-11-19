## 12:35 · decision · —

Close-out of Plan 00624. Issues #210 (unsigned park marker) and #211 (park markers read as unmerged) were already fixed in v3.75.0 and are closed: #210 by commit d2e73d0e9, #211 by Plans 00594 and 00622. Phase 1 reproduced each scenario on main and found nothing left to fix (subagent-reports/repro-findings.md).

The Phase 2 design (record the park under refs/parked/<name> so the branch gets no marker commit) was a coordinator's suggestion, not an owner request. The owner wants no drift into new features, so Phase 2 is not built and is closed as not needed. DESIGN-ref-park.md stays as a record, marked not adopted. Tasks 1.2 and 2.1 to 3.2 were not done and are closed as not needed.

No source code changed, so there are no release-bound consequences and no release note.
