# Callout: the ccy supervisor no longer disables a plugin because the host was busy, and says why when it does

**Plan**: 00603
**Audience**: client projects

On a heavily loaded host the policy worker can go unscheduled for longer than a plugin hook's time budget plus grace. The supervisor read the stale in-hook marker as a plugin stuck inside a hook and disabled the plugin for the rest of the session, with nothing in `claude-supervise-worker.err.log` and a notice saying no action was needed. For `ccy-lifecycle` that silently switched off the relaunch on a team join, the max-age restart and the deadline notice.

A wedge is now declared only when the same marker is seen at two consecutive silent ticks and the worker's CPU time did not advance between them. A plugin disabled for an exception, a bad result, an overrun or a wedge comes back at the next worker restart after the one the failure caused, or after 120 ticks the worker answered cleanly (`CCY_PLUGIN_REENABLE_CLEAN_TICKS` changes the count). A load refusal, a repeated unhonoured exit request and a host fault still keep the plugin off. Every disable now writes a line to `claude-supervise-worker.err.log` with the marker's age and the host load averages, and the notice names the cause, the log path and what is off while the plugin is disabled.

`PluginTestHarness` also no longer writes to the live worker error log: a hook that raises under it is logged under the harness's `work_dir`.

The host-side parts take effect when the ccy session is next started; the notice text reloads with the policy worker.
