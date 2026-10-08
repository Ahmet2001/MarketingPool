# Text report

Runs 4 step(s): demo.word_count, text.keywords, demo.headline, text.report.

## Install

```
/agent pack install <path to this folder>
```

The tool is called `text_report`. It is one Python file and needs nothing from the workflow factory.

## File inputs

`source` accept an https address, an object {"filename": ..., "content_base64": ...}, an asset id written as asset:<id>, or a local path in a folder the host allows. Local paths are refused unless the folder is listed in `STUDIO_FILE_ROOTS`. Downloads are https only, limited to public hosts and to `STUDIO_MAX_FILE_MB` (default 100).

## Where runs go

`STUDIO_TOOL_HOME` (default: the system temp folder, `studio_tools/`). Each call gets its own run folder, returned as `run_folder`.

## The agent

This pack is an `agent_bundle`: besides the tool it adds a sub-agent named `text_report_agent` that owns it, so the orchestrator can delegate to `text_report_agent` to run the workflow. The agent reads its sub-agents at start-up, so restart it after installing.
