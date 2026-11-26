# Callout: delete-branch accepts a branch that is a held commit plus empty commits

**Plan**: 00474
**Audience**: everyone

`delete-branch` already treated a local branch as safe to delete when a branch the remote still holds contains its tip. A branch that was a pushed branch's tip plus only empty commits (park commits, for example) was refused, because its own tip is held by no remote ref. The proof now strips the run of empty commits at the top of the tip, and asks whether a live remote ref holds the commit underneath. A branch with any real commit above that point, a merge commit in the run, or nothing remote holding the commit beneath it is still refused.
