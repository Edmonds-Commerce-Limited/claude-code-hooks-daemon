# Callout: the upgrade restores dropped opt-in handlers before it restarts the daemon

**Plan**: 00474
**Audience**: client projects

When an upgrade would switch off an opt-in handler that was running, the upgrade writes `enabled: true` for it so the project keeps what it ran before. That edit used to happen after the upgrade had restarted the daemon, so the restarted daemon ran without those handlers until someone restarted it again, and the upgrade printed RESTART THE DAEMON. The upgrade now makes the edit inside the version-specific step, after the new virtual environment is verified and before hooks are deployed and the daemon is restarted, so the restarted daemon already has the restored handlers on. The restored-handler report and the upgrade summary still list them, and no restart is asked for. If the restore cannot run (a target without the step, or an error), the upgrade continues and falls back to the earlier behaviour: the outer script applies the restore and asks for the restart.
