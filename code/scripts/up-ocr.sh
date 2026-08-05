#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  REPO_ROOT="${SCRIPT_DIR}"
else
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
ENV_FILE="${1:-${REPO_ROOT}/.env}"
source "${REPO_ROOT}/sewpg-bid-backend/onlyoffice/image-policy.sh"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${REPO_ROOT}/.env.example first." >&2
  exit 1
fi

if ! docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"'; then
  cat >&2 <<'EOF'
NVIDIA Docker runtime was not found.

baidu/Unlimited-OCR is started by vLLM on the configured OCR GPU, so this service
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

require_expected_onlyoffice_image \
  "${ENV_FILE}" "${ONLYOFFICE_DEV_IMAGE_DEFAULT}" \
  "ONLYOFFICE_IMAGE=${ONLYOFFICE_DEV_IMAGE_DEFAULT}" "${COMPOSE_ARGS[@]}"
configure_compose_build_compat_args
docker compose "${COMPOSE_ARGS[@]}" build \
  ${COMPOSE_BUILD_PROVENANCE_ARG:+"${COMPOSE_BUILD_PROVENANCE_ARG}"} \
  fastapi docling-worker opencode web onlyoffice
docker compose "${COMPOSE_ARGS[@]}" up -d --no-build
