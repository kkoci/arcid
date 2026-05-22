# ArcID agent container — runs the FastAPI backend inside a TDX CVM.
#
# Build:   docker build -t arcid/agent:0.1.0 -f phala/Dockerfile .
# Run:     docker run --rm -p 8000:8000 --env-file .env arcid/agent:0.1.0

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# system deps for cryptography / web3 wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY artifacts /app/artifacts
COPY deployments /app/deployments

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
