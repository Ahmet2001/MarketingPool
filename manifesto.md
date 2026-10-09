# Manifesto

### Fitting an agent to a system, and sharing what makes it fit

## 1. The idea

A language model on its own can talk. To be useful inside a real system it has to be **fitted** to that system: it needs the right instructions, the right tools, a way to read what is happening there, a way to act on it, and limits on what it may do.

This project is about that fitting. Not one agent for one job, but a way to **specialise an agent for a domain and connect it to a system**, and to keep the parts that do this small, separate, open and replaceable.

Today the domain we have worked in is marketing. Nothing in the shape of the system is marketing-specific. The same pieces could be fitted to trading, to human resources, to support, to operations. What changes is the instructions, the tools and the connections, not the architecture.

## 2. Four parts, none of them a placeholder

**Ethgent (the agent).** A customisable agent: an orchestrator model that delegates to sub-agents, which own tools. Agents and tools are described in YAML and travel as packs. You can create, edit and remove them from a terminal, and you can pull agents, sub-agents and tools from another repository. Ethgent comes tuned for social media, but that is a configuration, not its identity. It is a stand-alone project and is useful by itself.

**Marketing Agent Assets (the connection, and the open pool).** The layer that joins the agent to a system. Workers that hold credentials and talk to platforms, connectors, toolboxes, schemas, decision guides, and a small contract (`asset-pool`) for exposing your own app. It is also an **open pool**. There is no single "asset". Anyone can add their own tool, connector, worker or guide, so that nobody has to build the same integration alone. That open, shared character is a core part of the project.

**MarketingStudio (the factory).** Where capabilities are turned into new capabilities. A person writes small engines and joins them into workflows, checks and runs them locally, and exports the result as a neutral bundle. Small adapters reshape the bundle for a consumer: an agent pack, an agent bundle, tool definitions, a job handler, a worker, an MCP server. The Studio feeds the agent directly (an exported pack installs into Ethgent with one command) and the connection (workers and job handlers); it depends on neither the agent nor the pool.

**MarketingPool (the worked example).** The agent and the assets, put together and run with Docker on one machine. It is an example of the combination, not a product that all other parts must live inside. It shows that the combination works, and how.

## 3. What happens when they meet

When the agent and the assets are joined to a system, the loop closes:

- the model gets **feedback**: it can read data from the system and from the outside world;
- the model can **give something back**: it can write to the system and act outside it.

Connect it to an app and the agent can collect what the app has, make content from it and publish it, with the app staying the source of truth.

## 4. Principles

**Reason when necessary, execute deterministically whenever possible.** Most work is a repeatable process. A process that is already known should not be rediscovered by a model on every run. The Studio turns such processes into workflows that run without an agent; the agent decides what to run and when.

**The agent does not hold the keys.** Credentials live in workers. The agent writes a request; a worker that owns the credentials checks it and acts. Read-only data requests are checked against an allowlist.

**What changes the outside world needs approval.** Publishing, replying, following and similar actions are gated at call time by the host (a person, or an explicit grant on the job), never by the model and never by a sentence in a prompt.

**Every part works without the others.** The agent runs without the pool. The pool runs without the Studio. A workflow exported from the Studio does not need the Studio, the pool or Ethgent to run. Parts connect through plain files and small contracts.

**Open by construction.** Most of what can be contributed is declarative: a manifest entry, a guide, a schema, a pack. You should not have to change a worker to share something useful.

**Say what is real.** Each repository states what has been run and what has not. A capability that was never executed is not described as working.

## 5. Where things stand

Working and checked on one machine: a workflow written in the Studio, exported, installed into the pool and used by the agent as a tool, including one that needs approval, one that takes a file and one that needs a package; the agent running as a queue worker on a local Postgres-based queue with a real model; read-only data requests refused when they would write.

Not done: real publishing to a platform, real platform data (needs keys), the Studio being used by an agent (planned, deliberately not started), approvals over MCP, a single shared agent codebase (the agent exists in more than one copy today).

Other domains such as trading or HR are a direction the architecture allows, not something built.

## 6. Direction

We expect the human role to move from building every operation toward setting goals, limits, budgets and approval rules, with agents doing more of the fitting themselves. That is a direction, not a claim that autonomous agents are already reliable. Each step has to be shown, not asserted.

*Fit it to your system. Share what you build. Keep the keys with the workers and the decisions with the people.*
