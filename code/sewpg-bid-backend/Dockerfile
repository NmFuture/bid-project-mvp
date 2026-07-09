FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG HF_ENDPOINT=https://hf-mirror.com

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORMAT_CLEANER_ALLOW_SYSTEM_PY=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    BID_DOCLING_ARTIFACTS_PATH=/opt/docling-models

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-noto-cjk \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY scripts/download_docling_models.py ./scripts/download_docling_models.py
RUN --mount=type=cache,target=/root/.cache/huggingface \
    python scripts/download_docling_models.py /opt/docling-models --quiet

COPY app ./app
COPY scripts ./scripts
COPY opencode/skills ./opencode/skills

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
