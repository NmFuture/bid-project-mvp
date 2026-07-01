#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${SCRIPT_DIR}/.env.example first." >&2
  exit 1
fi

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${SCRIPT_DIR}/docker-compose.yml" \
  up -d --no-build

echo
echo "Product is starting at: http://127.0.0.1/"
echo "OCR is not started on this machine. Use start-ocr.sh on an NVIDIA GPU host."
