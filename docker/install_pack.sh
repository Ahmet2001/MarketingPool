#!/bin/sh
# Install an agent pack from ./packs into the running agent, then restart it so it reads the new sub-agent.
#   docker/install_pack.sh text_summary [--overwrite] [--no-deps]
#
# If the pack has a requirements.txt (the workflow's engines need Python packages), they are installed into
# /data/site-packages on the agent's volume, which is on PYTHONPATH. --no-deps skips that step.
set -e
PACK="$1"; shift || true
[ -n "$PACK" ] || { echo "usage: docker/install_pack.sh <folder under packs/> [--overwrite] [--no-deps]"; exit 2; }
OVERWRITE=False; DEPS=yes
for flag in "$@"; do
  case "$flag" in
    --overwrite) OVERWRITE=True ;;
    --no-deps) DEPS=no ;;
    *) echo "unknown option: $flag"; exit 2 ;;
  esac
done
cd "$(dirname "$0")/.."
if [ -f "packs/$PACK/requirements.txt" ]; then
  if [ "$DEPS" = yes ]; then
    echo "installing Python packages for $PACK: $(tr '\n' ' ' < "packs/$PACK/requirements.txt")"
    docker compose exec -T agent pip install --quiet --target /data/site-packages -r "/packs/$PACK/requirements.txt"
  else
    echo "skipping the Python packages of $PACK (--no-deps)"
  fi
fi
docker compose exec -T agent python -c "
from MarketingApp.llms.agent_studio import install_agent_pack, preview_agent_pack
p = preview_agent_pack('/packs/$PACK')
for line in p.get('errors', []): print('ERROR:', line)
for line in p.get('warnings', []): print('warning:', line)
r = install_agent_pack('/packs/$PACK', overwrite=$OVERWRITE)['pack']
print('installed:', r['name'], '| agents:', r['installed_agents'], '| tools:', r['installed_tools'])
"
docker compose restart agent
