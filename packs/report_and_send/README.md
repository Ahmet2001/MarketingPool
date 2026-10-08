# Report and send

Summarises a text into a short report and sends it to a recipient. Sending needs approval.

## Install

```
/agent pack install <path to this folder>
```

The tool is called `report_and_send`. It is one Python file and needs nothing from the workflow factory.

## Approval

This workflow changes something outside the machine (send: outbox.send). Ask the user to confirm first; call again with approve=true only after they said yes.

## Where runs go

`STUDIO_TOOL_HOME` (default: the system temp folder, `studio_tools/`). Each call gets its own run folder, returned as `run_folder`.

## The agent

This pack is an `agent_bundle`: besides the tool it adds a sub-agent named `report_and_send_agent` that owns it, so the orchestrator can delegate to `report_and_send_agent` to run the workflow. The agent reads its sub-agents at start-up, so restart it after installing.
