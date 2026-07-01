#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

ENV_FILE="${1:-${ROOT_DIR}/.env}"
ENABLE_OCR="${ENABLE_OCR:-false}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${ROOT_DIR}/.env.airgap.example first." >&2
  exit 1
fi

compose_args=(
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.airgap.yml"
)

if [[ "${ENABLE_OCR}" == "1" || "${ENABLE_OCR}" == "true" || "${ENABLE_OCR}" == "yes" ]]; then
  mkdir -p "${ROOT_DIR}/.localdata/ocr/huggingface"
  compose_args+=(
    -f "${ROOT_DIR}/docker-compose.ocr.yml"
    -f "${ROOT_DIR}/docker-compose.ocr.airgap.yml"
  )
fi

docker compose "${compose_args[@]}" up -d --no-build
