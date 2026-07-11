#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${REPO_ROOT}/.env.example first." >&2
  exit 1
fi

if ! docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"'; then
  cat >&2 <<'EOF'
NVIDIA Docker runtime was not found.

baidu/Unlimited-OCR is started by vLLM with "gpus: all", so this service
requires an NVIDIA GPU host with NVIDIA Container Toolkit installed.

The main product can still run without OCR:
  docker compose --env-file .env -f docker-compose.yml up -d --no-build
EOF
  exit 1
fi

mkdir -p "${REPO_ROOT}/.localdata/ocr/huggingface"

COMPOSE_ARGS=(
  --env-file "${ENV_FILE}" \
  -f "${REPO_ROOT}/docker-compose.yml" \
  -f "${REPO_ROOT}/docker-compose.ocr.yml"
)

docker compose "${COMPOSE_ARGS[@]}" build fastapi worker opencode web
docker compose "${COMPOSE_ARGS[@]}" up -d --no-build
