#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

ENV_FILE="${1:-${ROOT_DIR}/.env}"
ACTION="${2:-up}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${ROOT_DIR}/.env.airgap.example and inject secrets first." >&2
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "5090 deployment requires an x86_64 host." >&2
  exit 1
fi

for command_name in docker nvidia-smi python3; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is unavailable to the current user." >&2
  exit 1
fi

if ! docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"'; then
  echo "NVIDIA Container Runtime is not registered with Docker." >&2
  exit 1
fi

if ! nvidia-smi --query-gpu=index --format=csv,noheader | grep -qx '0'; then
  echo "GPU 0 is not visible on the host." >&2
  exit 1
fi

env_value() {
  awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${ENV_FILE}"
}

require_nonempty() {
  if [[ -z "$(env_value "$1")" ]]; then
    echo "Required deployment variable is empty: $1" >&2
    exit 1
  fi
}

require_changed() {
  if [[ "$(env_value "$1")" == "$2" ]]; then
    echo "Deployment variable still uses its example default: $1" >&2
    exit 1
  fi
}

for variable_name in \
  INTERNAL_LLM_BASE_URL \
  INTERNAL_LLM_API_KEY \
  DEFAULT_LLM_MODEL \
  POSTGRES_PASSWORD \
  MINIO_ROOT_PASSWORD \
  AUTH_ADMIN_PASSWORD; do
  require_nonempty "${variable_name}"
done
require_changed POSTGRES_PASSWORD bidpass
require_changed MINIO_ROOT_PASSWORD minioadmin
require_changed AUTH_ADMIN_PASSWORD 123456

mkdir -p "${ROOT_DIR}/.localdata/ocr/huggingface"
if [[ -z "$(find "${ROOT_DIR}/.localdata/ocr/huggingface" -mindepth 1 -print -quit)" ]]; then
  echo "Warning: OCR model cache is empty; a truly offline start requires preloaded model weights." >&2
fi

compose_args=(
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.airgap.yml"
  -f "${ROOT_DIR}/docker-compose.ocr.yml"
  -f "${ROOT_DIR}/docker-compose.ocr.airgap.yml"
  -f "${ROOT_DIR}/docker-compose.5090.yml"
)

docker compose "${compose_args[@]}" config --quiet
docker compose "${compose_args[@]}" config --format json | python3 -c '
import json
import sys

config = json.load(sys.stdin)
for service_name in ("docling-worker", "ocr"):
    service = config["services"][service_name]
    devices = service["deploy"]["resources"]["reservations"]["devices"]
    if len(devices) != 1 or devices[0].get("device_ids") != ["0"]:
        raise SystemExit(f"{service_name} is not exclusively bound to GPU 0")
    environment = service.get("environment") or {}
    if environment.get("NVIDIA_VISIBLE_DEVICES") != "0" or environment.get("CUDA_VISIBLE_DEVICES") != "0":
        raise SystemExit(f"{service_name} GPU visibility is not restricted to GPU 0")
'

if [[ "${ACTION}" == "--check-only" ]]; then
  echo "5090 deployment preflight passed. No containers were changed."
  exit 0
fi

if [[ "${ACTION}" != "up" ]]; then
  echo "Unknown action: ${ACTION}. Use 'up' or '--check-only'." >&2
  exit 1
fi

docker compose "${compose_args[@]}" up -d --no-build
