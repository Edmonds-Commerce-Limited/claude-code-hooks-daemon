# Callout: a commit gate that ran out of time says so instead of reporting a finding

**Plan**: 00474
**Audience**: everyone

`conflict_marker_commit_gate` fails closed when `git` times out reading a commit. It used to report the same reason as a real finding, so an agent could not tell "could not check" from "found something". It now has its own rule ID, `R-CONFLICT-MARKER-SCAN-TIMED-OUT`, whose reason says git did not answer within its 5 s limit, that no conflict marker was found and the content needs no edit, and to retry the same commit. It still denies, and no timeout changed. A real finding keeps `R-CONFLICT-MARKER-COMMIT`. `bin/hooks-daemon explain-rule` describes the rule. The secret guard no longer denies a scan that ran out of budget (see "The secret, quarantine and containment guards deny only on a finding" below).
