FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code + config.
COPY statuspack ./statuspack
COPY services.yaml ./services.yaml

EXPOSE 8000

# Datadog credentials, ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL are supplied at
# runtime via environment variables (see .env.example) — never baked into the image.
CMD ["uvicorn", "statuspack.app:app", "--host", "0.0.0.0", "--port", "8000"]
