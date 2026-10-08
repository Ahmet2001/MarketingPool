# Build context: marketing-agent-assets/ (the worker reads ../toolboxes/*/manifest.yaml).
FROM python:3.12-slim
WORKDIR /app
COPY platform_data_worker/requirements.txt platform_data_worker/requirements.txt
RUN pip install --no-cache-dir -r platform_data_worker/requirements.txt
COPY platform_data_worker platform_data_worker
COPY toolboxes toolboxes
ENV TOOLBOXES_DIR=/app/toolboxes PYTHONUNBUFFERED=1
CMD ["python", "-m", "platform_data_worker.worker"]
