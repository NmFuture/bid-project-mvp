#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE_DIR="${1:-${REPO_ROOT}/offline-dist}"
TAG="${2:-offline-$(date +%Y%m%d%H%M)}"
ONLYOFFICE_SOURCE_IMAGE="${ONLYOFFICE_SOURCE_IMAGE:-onlyoffice/documentserver:9.3.1.2}"
REDIS_SOURCE_IMAGE="${REDIS_SOURCE_IMAGE:-redis:7-alpine}"
INCLUDE_OCR="${INCLUDE_OCR:-false}"
OCR_SOURCE_IMAGE="${OCR_SOURCE_IMAGE:-vllm/vllm-openai:unlimited-ocr}"

mkdir -p "${BUNDLE_DIR}/images"

export APP_IMAGE_TAG="${TAG}"
export WEB_IMAGE="sewpg-bid/web:${TAG}"
export FASTAPI_IMAGE="sewpg-bid/fastapi:${TAG}"
export DOCLING_IMAGE="sewpg-bid/docling-worker:${TAG}"
export OPENCODE_IMAGE="sewpg-bid/opencode:${TAG}"
export ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:9.3.1.2"
export REDIS_IMAGE="${REDIS_SOURCE_IMAGE}"
export OCR_IMAGE="${OCR_SOURCE_IMAGE}"

IMAGE_TAR="${BUNDLE_DIR}/images/sewpg-bid-images-${TAG}.tar"
MANIFEST_PATH="${BUNDLE_DIR}/bundle-manifest.json"

echo "==> Building application images..."
docker compose -f "${REPO_ROOT}/docker-compose.yml" build web fastapi docling-worker opencode

if docker image inspect "${ONLYOFFICE_SOURCE_IMAGE}" >/dev/null 2>&1; then
  echo "==> Reusing local OnlyOffice image..."
else
  echo "==> Pulling OnlyOffice image..."
  docker pull "${ONLYOFFICE_SOURCE_IMAGE}"
fi

echo "==> Retagging OnlyOffice image..."
docker tag "${ONLYOFFICE_SOURCE_IMAGE}" "${ONLYOFFICE_IMAGE}"

if docker image inspect "${REDIS_SOURCE_IMAGE}" >/dev/null 2>&1; then
  echo "==> Reusing local Redis image..."
else
  echo "==> Pulling Redis image..."
  docker pull "${REDIS_SOURCE_IMAGE}"
fi

if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then
  if docker image inspect "${OCR_SOURCE_IMAGE}" >/dev/null 2>&1; then
    echo "==> Reusing local OCR vLLM image..."
  else
    echo "==> Pulling OCR vLLM image..."
    docker pull "${OCR_SOURCE_IMAGE}"
  fi
fi

rm -f "${IMAGE_TAR}"

echo "==> Exporting image bundle..."
save_images=(
  "${WEB_IMAGE}"
  "${FASTAPI_IMAGE}"
  "${DOCLING_IMAGE}"
  "${OPENCODE_IMAGE}"
  "${ONLYOFFICE_IMAGE}"
  "${REDIS_IMAGE}"
)
if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then
  save_images+=("${OCR_SOURCE_IMAGE}")
fi
docker save -o "${IMAGE_TAR}" "${save_images[@]}"

cp "${REPO_ROOT}/docker-compose.yml" "${BUNDLE_DIR}/docker-compose.yml"
cp "${REPO_ROOT}/docker-compose.airgap.yml" "${BUNDLE_DIR}/docker-compose.airgap.yml"
cp "${REPO_ROOT}/docker-compose.ocr.yml" "${BUNDLE_DIR}/docker-compose.ocr.yml"
cp "${REPO_ROOT}/docker-compose.ocr.airgap.yml" "${BUNDLE_DIR}/docker-compose.ocr.airgap.yml"
cp "${REPO_ROOT}/.env.airgap.example" "${BUNDLE_DIR}/.env.airgap.example"
mkdir -p "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice"
cp "${REPO_ROOT}/sewpg-bid-backend/onlyoffice/docker-entrypoint.sh" \
  "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice/docker-entrypoint.sh"
chmod +x "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice/docker-entrypoint.sh"
cp "${REPO_ROOT}/scripts/load-airgap-images.sh" "${BUNDLE_DIR}/load-airgap-images.sh"
cp "${REPO_ROOT}/scripts/up-airgap.sh" "${BUNDLE_DIR}/up-airgap.sh"
cp "${REPO_ROOT}/scripts/up-ocr.sh" "${BUNDLE_DIR}/up-ocr.sh"

cat > "${MANIFEST_PATH}" <<EOF
{
  "createdAt": "$(date +%Y-%m-%dT%H:%M:%S)",
  "bundleFile": "$(basename "${IMAGE_TAR}")",
  "images": [
    "${WEB_IMAGE}",
    "${FASTAPI_IMAGE}",
    "${DOCLING_IMAGE}",
    "${OPENCODE_IMAGE}",
    "${ONLYOFFICE_IMAGE}",
    "${REDIS_IMAGE}"$(if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then printf ',\n    "%s"' "${OCR_SOURCE_IMAGE}"; fi)
  ],
  "composeFiles": [
    "docker-compose.yml",
    "docker-compose.airgap.yml",
    "docker-compose.ocr.yml",
    "docker-compose.ocr.airgap.yml"
  ],
  "envTemplate": ".env.airgap.example"
}
EOF

echo
echo "Air-gapped bundle is ready:"
echo "  Bundle dir : ${BUNDLE_DIR}"
echo "  Image tar  : ${IMAGE_TAR}"
echo "  Env sample : ${BUNDLE_DIR}/.env.airgap.example"
