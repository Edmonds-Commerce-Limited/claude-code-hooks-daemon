## 21:50 · decision · —

Rulings on the second client seat and the release decision, settled by a fable sub-agent under the owner's delegation, 2026-11-19. NOT the owner's own words; a later owner message overturns any of them. No release was run or started, no remote and no client seat was touched, nothing was deleted, nothing was built. Full text: DESIGN.md section 7.

Second client seat: it no longer blocks the plan. Each waiting task is re-cut to be provable in this repository; a seat's report is added as evidence when it comes.

- Task 1.3: closed. Review round 1 is DESIGN section 6, and the built phases ran on two client seats through release candidates. The open section 4 questions are answered there, sized by the sweep preview, or ruled here.
- Task 4.6: a stack counts as one stream against the open cap up to `branches.wip.stack_max_depth` (default 5); each link past it counts one more. Grouping reads tips only, no forge call. A fork ends a chain. The sweep, the preflight and the creation guard share one count, pinned by a test.
- Task 5.1: proven end to end in the client-mode fixture against a local bare remote (track, move, moved-ref report, re-track, one-step return; a sha pin; a failed listing). The stop/build/start handover is Plan 00535's and does not hold this plan open.

Release decision:

- The question journalled on 15 November (release over in-flight plans) is overtaken: release 3.75.0 was cut afterwards and carries this plan's notes 075 to 083.
- This plan neither asks for a release nor holds one back.
- The next release stays under the owner's own typed conditional approval recorded in Plan 00623's journal, with its conditions and its lapse. This ruling does not extend, widen or start it.
- The surviving-content remote-delete branch (`agent-a20c91c23eca4e56e-43e33957`) becomes ordinary work, new Task 3.8: bring it up to main, reconcile it with Plan 00626's proof code, move its release note into the pending holding area under a free number, targeted QA, adversarial security review, then merge with --no-ff. Never while a release state file exists. It was not merged here.

Still needs the human: starting any release, and `accept-wip` if the slate check names this plan; a real seat's confirmation of Task 5.1 if the owner wants one on record (safe default: the fixture proof closes it).

First build slice: Task 4.6, failing tests for the stack grouping function over fixture repositories (a five-deep chain counts 1, a seven-deep chain counts 3, a fork, a parked link, remote-only tips).
