# MarketingPool

The marketing agent, the open asset pool it draws on, and a Docker setup that runs them together on one machine.

| Folder | What it is |
| --- | --- |
| [`agent/`](./agent) | The marketing agent. Run as a worker it polls the `agent_jobs` queue and also serves MCP. See its [`AGENT.md`](./agent/AGENT.md). |
| [`marketing-agent-assets/`](./marketing-agent-assets) | The open pool: queue workers, platform toolboxes, the app-connection kit (`asset-pool`), shared schemas, skills, examples. Contributions are welcome there; see its [README](./marketing-agent-assets/README.md#open-contribution). |
| [`docker-compose.yml`](./docker-compose.yml), [`docker/`](./docker) | Everything above on this machine, with a local queue in place of Supabase. See [`docker/README.md`](./docker/README.md). |
| [`manifesto.md`](./manifesto.md) | Why these pieces exist and how they relate. |

```bash
python3 docker/make_env.py                       # once: local queue secrets -> .env (never committed)
cp env/agent.env.example env/agent.env           # then put your model key in it (never committed)
docker compose up -d --build queue platform-data-worker social-media-worker agent
```

Secrets stay out of the repository: `.env` and `env/*.env` are ignored; only the `*.example` files are committed.

The workflow factory that can export workflows for these workers is a separate project, [MarketingStudio](https://github.com/Ahmet2001/MarketingStudio).
