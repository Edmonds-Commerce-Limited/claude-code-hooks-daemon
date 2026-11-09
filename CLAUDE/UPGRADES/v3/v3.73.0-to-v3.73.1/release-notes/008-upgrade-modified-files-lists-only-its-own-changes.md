# Callout: the upgrade's `modified_files` lists only the files the upgrade changed

**Plan**: 00474
**Audience**: client projects

`UPGRADE_METADATA`'s `modified_files` used to name every uncommitted file in the project, so an upgrade run while another agent had work in progress listed that work too, and a gate that exempts listed paths as daemon-owned exempted it silently. The upgrade now records which files were already uncommitted, with a hash of each one's content, before it writes anything, and lists only paths it created, modified or deleted, including a pre-existing uncommitted file it then changed again. If you have been trimming `modified_files` by hand before pasting it into the upgrade commit, you can stop.
