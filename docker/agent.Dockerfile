# The marketing agent as a worker (python -m MarketingApp.worker). Build context: agent/
#
# Layers are ordered from "never changes" to "changes often", so an edit only rebuilds what comes after it:
# system packages -> Chromium -> Python packages -> git -> the code.
FROM python:3.12-slim
WORKDIR /app

# A virtual screen: pyautogui/mss want a display even when nobody looks at it.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth scrot python3-tk python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Chromium is the biggest download. It depends only on the playwright version, so it has its own layer
# and is not repeated when other requirements change. Keep this in step with requirements.txt (checked below).
ARG PLAYWRIGHT_VERSION=1.58.0
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install playwright==${PLAYWRIGHT_VERSION} && playwright install --with-deps chromium

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && python -c "import importlib.metadata as m, sys; v=m.version('playwright'); sys.exit(0 if v=='${PLAYWRIGHT_VERSION}' else 'requirements.txt pins playwright '+v+', but the Chromium layer was built for ${PLAYWRIGHT_VERSION}: update PLAYWRIGHT_VERSION in docker/agent.Dockerfile')"

# Installing agent packs from GitHub (`/agent pack install github:...`) needs git.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY . .
# config/agents.yaml pins some sub-agents to a Gemma model name that other providers reject. "default" means
# "use SUBMODEL_MODEL_NAME from the environment". The source file is left as it is; only the image changes.
RUN sed -i 's/^  model: gemma-4-26b-a4b-it$/  model: default/' MarketingApp/config/agents.yaml
ENV PYTHONUNBUFFERED=1 ETHGENT_WORKSPACE_DIR=/data/workspace ETHGENT_CONFIG_DIR=/data/config PYTHONPATH=/data/site-packages DISPLAY=:99
# Python packages that exported workflows need are installed into /data/site-packages (see docker/install_pack.sh),
# so they also survive the container being recreated and need no image rebuild.
# The config (agents.yaml, custom_tools.yaml, ...) lives on the /data volume so that installed packs survive a
# container being recreated. The image's defaults are copied in on first start; files already there are kept.
# xvfb-run hangs here without ever starting Python, so the virtual screen is started by hand.
CMD ["sh", "-c", "mkdir -p /data/config && cp -rn /app/MarketingApp/config/. /data/config/; rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & sleep 2; exec python -m MarketingApp.worker"]
