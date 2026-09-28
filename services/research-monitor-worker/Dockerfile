FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY apps/api /app/apps/api
COPY services/research-monitor-worker /app/services/research-monitor-worker
CMD ["python", "/app/services/research-monitor-worker/main.py"]
