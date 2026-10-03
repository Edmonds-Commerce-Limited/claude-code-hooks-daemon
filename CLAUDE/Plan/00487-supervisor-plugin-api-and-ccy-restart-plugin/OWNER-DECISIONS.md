# Plan 00487: decisions for the owner

Each item here is the owner's call. An agent adds the item, with its options, a recommendation and the evidence, then commits and pushes. The owner answers in the **Answer** line, or tells any session the answer, and that session records it. No agent acts on an item until it has an answer.

## D1. The fedora-desktop PR

`feature/ccy-hooks-daemon-plugin` holds the ccy plugin and the launcher changes. Should a PR be opened, and should it be merged?

- **Recommendation:** open the PR once `qa-all.bash` and the live test pass on the host. Merging is a separate step.
- **Evidence:** the OWNER-LIVE-TEST.md results and the qa-all output, recorded in this plan's JOURNAL.
- **Answer:** _pending_

## D2. Tasks 1.4 and 1.5 (in-container `Restart` and the host half)

These serve the credential switch (fedora-desktop Plan 00146), not this plan's goals. Should they stay here, move to fedora-desktop Plan 00146, or move to a new hooks-daemon plan?

- **Recommendation:** move them to a new hooks-daemon plan, so that 00487 can close when the live test passes. The API code lives in this repository.
- **Answer:** _pending_

## D3. The agent rulings in [DECISIONS.md](DECISIONS.md)

The rulings in DECISIONS.md were made by an agent while the owner was away. Should each one be confirmed or reversed?

1. Release first. This is done, so nothing is left to decide.
2. Push the fedora-desktop branch, but open no PR. D1 supersedes this.
3. ccy keeps its plugin in its own repository and names it with `--plugin`.
4. Restart policy:
   - maximum age is off unless set;
   - a warning goes out 10 minutes before the restart;
   - there is no forced restart of a busy session;
   - at most 3 restarts per hour.
5. An update restarts through a host relaunch on exit 75.

- **Answer:** _pending_

## D4. A hooks-daemon release carrying the API

Other projects get the plugin API only from a release. A release starts only when the owner types `/release`.

- **Recommendation:** release after the live test passes, so that the release carries a tested API.
- **Answer:** _pending_
