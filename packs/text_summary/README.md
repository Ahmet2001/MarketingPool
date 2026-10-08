# Text summary

Counts the words of a text and lists its most frequent words as a short Markdown report.

## Install

```
/agent pack install <path to this folder>
```

The tool is called `text_summary`. It is one Python file and needs nothing from the workflow factory.

## Where runs go

`STUDIO_TOOL_HOME` (default: the system temp folder, `studio_tools/`). Each call gets its own run folder, returned as `run_folder`.

## The agent

This pack is an `agent_bundle`: besides the tool it adds a sub-agent named `text_summary_agent` that owns it, so the orchestrator can delegate to `text_summary_agent` to run the workflow. The agent reads its sub-agents at start-up, so restart it after installing.
