#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
source "${ROOT_DIR}/sewpg-bid-backend/onlyoffice/image-policy.sh"

ENV_FILE="${1:-${ROOT_DIR}/.env}"
ACTION="${2:-up}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Create it from ${ROOT_DIR}/.env.airgap.example and inject secrets first." >&2
  exit 1
fi

case "${ACTION}" in
  up|--check-only)
    DEPLOY_MODE="online"
    ;;
  --offline|--check-offline)
    DEPLOY_MODE="offline"
    ;;
  *)
    echo "Unknown action: ${ACTION}. Use 'up', '--check-only', '--offline', or '--check-offline'." >&2
    exit 1
    ;;
esac

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
  OPENCODE_MODEL_ID \
  DATABASE_URL \
  POSTGRES_PASSWORD \
  MINIO_ROOT_PASSWORD \
  AUTH_ADMIN_PASSWORD; do
  require_nonempty "${variable_name}"
done
require_changed OPENCODE_MODEL_ID replace-with-your-internal-model
require_changed DEFAULT_LLM_MODEL replace-with-your-internal-model
require_changed DATABASE_URL postgresql+asyncpg://biduser:bidpass@postgres:5432/bidplatform
require_changed POSTGRES_PASSWORD bidpass
require_changed MINIO_ROOT_PASSWORD minioadmin
require_changed AUTH_ADMIN_PASSWORD 123456

if [[ "${DEPLOY_MODE}" == "online" ]]; then
  if ! git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Online deployment must run from a checked-out main worktree." >&2
    exit 1
  fi
  CURRENT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
  if git -C "${ROOT_DIR}" rev-parse --verify origin/main >/dev/null 2>&1 && \
    [[ "${CURRENT_SHA}" != "$(git -C "${ROOT_DIR}" rev-parse origin/main)" ]]; then
    echo "Current commit does not match origin/main; fetch and fast-forward main before deploying." >&2
    exit 1
  fi
  if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
    echo "The worktree has tracked or untracked changes; restore the approved main SHA before deploying." >&2
    exit 1
  fi

  RELEASE_TAG="main-${CURRENT_SHA:0:12}"
  export APP_IMAGE_TAG="${RELEASE_TAG}"
  export WEB_IMAGE="sewpg-bid/web:${RELEASE_TAG}"
  export FASTAPI_IMAGE="sewpg-bid/fastapi:${RELEASE_TAG}"
  export DOCLING_IMAGE="sewpg-bid/docling-worker:${RELEASE_TAG}"
  export OPENCODE_IMAGE="sewpg-bid/opencode:${RELEASE_TAG}"
  export ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:${RELEASE_TAG}-fontpack-v1"
  export ONLYOFFICE_BASE_IMAGE="onlyoffice/documentserver:9.3.1.2@sha256:0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31"
  export ONLYOFFICE_FONT_BUILDER_IMAGE="debian:bookworm-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e"
  export ONLYOFFICE_BUILD_REVISION="${CURRENT_SHA}"
fi

mkdir -p "${ROOT_DIR}/.localdata/ocr/huggingface"
if [[ -z "$(find "${ROOT_DIR}/.localdata/ocr/huggingface" -mindepth 1 -print -quit)" ]]; then
  if [[ "${DEPLOY_MODE}" == "online" ]]; then
    echo "Notice: OCR model cache is empty; the OCR container will download weights on first start." >&2
  else
    echo "Warning: OCR model cache is empty; offline OCR requires preloaded model weights." >&2
  fi
fi

compose_args=(
  --env-file "${ENV_FILE}"
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/docker-compose.ocr.yml"
  -f "${ROOT_DIR}/docker-compose.5090.yml"
)

if [[ "${DEPLOY_MODE}" == "offline" ]]; then
  compose_args=(
    --env-file "${ENV_FILE}"
    -f "${ROOT_DIR}/docker-compose.yml"
    -f "${ROOT_DIR}/docker-compose.airgap.yml"
    -f "${ROOT_DIR}/docker-compose.ocr.yml"
    -f "${ROOT_DIR}/docker-compose.ocr.airgap.yml"
    -f "${ROOT_DIR}/docker-compose.5090.yml"
  )
  EXPECTED_ONLYOFFICE_IMAGE="$(onlyoffice_image_from_env_template "${ROOT_DIR}/.env.airgap.example")"
  ONLYOFFICE_MIGRATION_INSTRUCTION="copy ONLYOFFICE_IMAGE from ${ROOT_DIR}/.env.airgap.example"
else
  EXPECTED_ONLYOFFICE_IMAGE="${ONLYOFFICE_IMAGE}"
  ONLYOFFICE_MIGRATION_INSTRUCTION="ONLYOFFICE_IMAGE=${ONLYOFFICE_IMAGE}"
fi

require_expected_onlyoffice_image \
  "${ENV_FILE}" "${EXPECTED_ONLYOFFICE_IMAGE}" \
  "${ONLYOFFICE_MIGRATION_INSTRUCTION}" "${compose_args[@]}"
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

if [[ "${ACTION}" == "--check-only" || "${ACTION}" == "--check-offline" ]]; then
  echo "5090 ${DEPLOY_MODE} deployment preflight passed. No containers were changed."
  exit 0
fi

if [[ "${DEPLOY_MODE}" == "online" ]]; then
  echo "Deploying Git SHA: ${CURRENT_SHA} (${RELEASE_TAG})"
  docker compose "${compose_args[@]}" pull postgres redis minio ocr
  build_args=()
  if [[ "${REFRESH_BASE_IMAGES:-0}" == "1" ]]; then
    # --pull 会重新拉取基础镜像；基础镜像一旦更新，其后所有层的缓存链整体作废，
    # 且不可逆（本地基础镜像已被替换，事后去掉 --pull 也无法复用旧缓存）。
    # 代理带宽劣化时这会把每次部署变成全量重建，因此默认关闭，仅在需要更新
    # 基础镜像时显式开启，并选择网络良好的时段执行。
    echo "REFRESH_BASE_IMAGES=1: pulling base images, expect a full rebuild."
    build_args+=(--pull)
  fi
  docker compose "${compose_args[@]}" build --provenance=false \
    "${build_args[@]}" web fastapi docling-worker opencode onlyoffice
  ONLYOFFICE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${ONLYOFFICE_IMAGE}")"
  echo "OnlyOffice image ID: ${ONLYOFFICE_IMAGE_ID}"
fi

docker compose "${compose_args[@]}" up -d --no-build
