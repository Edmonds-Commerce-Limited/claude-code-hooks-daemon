# Callout: upgrading to a commit whose short SHA is all digits is no longer stopped as a "MAJOR version change"

**Plan**: 00474
**Audience**: client projects

An upgrade that names a commit rather than a tag records the commit's short SHA as its target. When that SHA happened to contain only decimal digits (about 1.5% of nine-character SHAs, for example `965951009`), `upgrade_version.sh` and the pre-deploy gate read it as release 965951009, reported "MAJOR version change: v3.x -> v965951009.x" and stopped the upgrade with exit 3 until the reading was confirmed. A release is now recognised only when it is `v`-prefixed (`v4`, `v3.74.0`) or dotted (`3.74.0`); an all-digit ref is a commit ref like any other, and the gate reads the target's version from the checkout as it already did for a SHA with letters in it.
