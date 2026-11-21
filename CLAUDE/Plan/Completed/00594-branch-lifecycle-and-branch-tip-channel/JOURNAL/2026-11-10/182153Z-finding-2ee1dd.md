## 18:21 · finding · —

v3.74.0 was released (tag on merge commit a7c632c2a) and the three held branches were then merged to main.

Release: the Step 10 review found five defects in code new to the release, and a re-review of the fixes found two more in the new home-branch notice. All seven were fixed on the release branch rather than deferred, so the CI run and the acceptance gates restarted twice. The merged tree equals the CI-passed tree.

Merges after the tag: fact-check-04 (plan docs), Task 5.1 and Tasks 3.1/3.2 with 4.7.

Findings worth keeping:

- Task 5.1's branch had passed its own review and QA, yet two suites it had not run failed on the merged tree. One enforces the Plan 00291 ruling that the branch-install gate's variable names stay out of handler text, which feeds the generated HOOKS-DAEMON.md: the "ref moved" advisory printed them. The advisory now tells the client to re-run the guarded install they used. The other registers `version_check` as an allowed reader of the venv metadata, with its reason. A branch's targeted QA has to include the suites that guard its neighbours, not only the files it touched.
- Task 4.7's test was written after its fix, so it was never seen failing.
- The branch-creation guard blocked the release branch itself until six stale merged agent branches were deleted behind recovery bundles and the two rc branches were kept with reasons.

Task 5.1 stays open: proof on the client test seat, and the stop/build/start handover that belongs to Plan 00535.
