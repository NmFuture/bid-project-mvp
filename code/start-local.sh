#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env}"
source "${SCRIPT_DIR}/sewpg-bid-backend/onlyoffice/image-policy.sh"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${SCRIPT_DIR}/.env.example first." >&2
  exit 1
fi

COMPOSE_ARGS=(
  --env-file "${ENV_FILE}" \
  -f "${SCRIPT_DIR}/docker-compose.yml"
)

require_expected_onlyoffice_image \
  "${ENV_FILE}" "${ONLYOFFICE_DEV_IMAGE_DEFAULT}" \
  "ONLYOFFICE_IMAGE=${ONLYOFFICE_DEV_IMAGE_DEFAULT}" "${COMPOSE_ARGS[@]}"
configure_compose_build_compat_args
docker compose "${COMPOSE_ARGS[@]}" build \
  ${COMPOSE_BUILD_PROVENANCE_ARG:+"${COMPOSE_BUILD_PROVENANCE_ARG}"} onlyoffice
docker compose "${COMPOSE_ARGS[@]}" up -d --no-build

echo
echo "Product is starting at: http://127.0.0.1/"
echo "OCR is not started on this machine. Use start-ocr.sh on an NVIDIA GPU host."
