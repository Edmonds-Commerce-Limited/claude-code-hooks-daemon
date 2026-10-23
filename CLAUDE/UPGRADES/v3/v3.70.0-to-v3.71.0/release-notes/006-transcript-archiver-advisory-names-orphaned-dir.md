# Callout: the removed `transcript_archiver` advisory now names the leftover directory

**Plan**: 00541
**Audience**: operators

If your config still carries a `transcript_archiver` key, the advisory the daemon prints for it now says what to clean up as well as what to delete from the config: delete `untracked/transcripts/` to reclaim the disk. Those archives are copies of transcripts you still have, so nothing is lost by removing them. (reported as issue #52)
