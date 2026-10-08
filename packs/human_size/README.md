# Human size

Writes a number of bytes in human units, for example 1.5 MB.

## Install

```
/agent pack install <path to this folder>
```

The tool is called `human_size`. It is one Python file and needs nothing from the workflow factory.

## Python packages

- `humanize`

## Where runs go

`STUDIO_TOOL_HOME` (default: the system temp folder, `studio_tools/`). Each call gets its own run folder, returned as `run_folder`.

## The agent

This pack is an `agent_bundle`: besides the tool it adds a sub-agent named `human_size_agent` that owns it, so the orchestrator can delegate to `human_size_agent` to run the workflow. The agent reads its sub-agents at start-up, so restart it after installing.
