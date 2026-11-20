# Callout: a finished agent whose report quotes a usage-limit sentence is no longer reported as killed

**Plan**: 00474
**Audience**: client projects

The prompt-time check for agents killed by a usage limit searched the whole task notification, so a completed agent whose report quoted the limit text drew a "re-brief it" notice. A notification whose status is completed is now ignored, and the limit sentence is looked for outside the agent's own result.
