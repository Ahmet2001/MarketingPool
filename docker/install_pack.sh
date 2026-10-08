#!/bin/sh
# Install an agent pack from ./packs into the running agent, then restart it so it reads the new sub-agent.
#   docker/install_pack.sh text_summary [--overwrite]
set -e
PACK="$1"; shift || true
[ -n "$PACK" ] || { echo "usage: docker/install_pack.sh <folder under packs/> [--overwrite]"; exit 2; }
OVERWRITE=False; [ "$1" = "--overwrite" ] && OVERWRITE=True
cd "$(dirname "$0")/.."
docker compose exec -T agent python -c "
from MarketingApp.llms.agent_studio import install_agent_pack, preview_agent_pack
p = preview_agent_pack('/packs/$PACK')
for line in p.get('errors', []): print('ERROR:', line)
for line in p.get('warnings', []): print('warning:', line)
r = install_agent_pack('/packs/$PACK', overwrite=$OVERWRITE)['pack']
print('installed:', r['name'], '| agents:', r['installed_agents'], '| tools:', r['installed_tools'])
"
docker compose restart agent
