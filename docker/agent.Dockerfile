# The marketing agent as a worker (python -m MarketingApp.worker). Build context: agent/
FROM python:3.12-slim
WORKDIR /app
# A virtual screen: pyautogui/mss want a display even when nobody looks at it.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth scrot python3-tk python3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium
COPY . .
# config/agents.yaml pins the sub-agents to a Gemma model name that other providers reject. "default" means
# "use SUBMODEL_MODEL_NAME from the environment". The source file is left as it is; only the image changes.
RUN sed -i 's/^  model: gemma-4-26b-a4b-it$/  model: default/' MarketingApp/config/agents.yaml
ENV PYTHONUNBUFFERED=1 MIMAR_WORKSPACE_DIR=/data/workspace DISPLAY=:99
# xvfb-run hangs here without ever starting Python, so the virtual screen is started by hand.
CMD ["sh", "-c", "rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & sleep 2; exec python -m MarketingApp.worker"]
