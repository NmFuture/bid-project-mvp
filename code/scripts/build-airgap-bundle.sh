#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE_DIR="${1:-${REPO_ROOT}/offline-dist}"
TAG="${2:-offline-$(date +%Y%m%d%H%M)}"
ONLYOFFICE_SOURCE_IMAGE="${ONLYOFFICE_SOURCE_IMAGE:-onlyoffice/documentserver:9.3.1.2}"

mkdir -p "${BUNDLE_DIR}/images"

export APP_IMAGE_TAG="${TAG}"
export WEB_IMAGE="sewpg-bid/web:${TAG}"
export FASTAPI_IMAGE="sewpg-bid/fastapi:${TAG}"
export OPENCODE_IMAGE="sewpg-bid/opencode:${TAG}"
export ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:9.3.1.2"

IMAGE_TAR="${BUNDLE_DIR}/images/sewpg-bid-images-${TAG}.tar"
MANIFEST_PATH="${BUNDLE_DIR}/bundle-manifest.json"

echo "==> Building application images..."
docker compose -f "${REPO_ROOT}/docker-compose.yml" build web fastapi opencode

if docker image inspect "${ONLYOFFICE_SOURCE_IMAGE}" >/dev/null 2>&1; then
  echo "==> Reusing local OnlyOffice image..."
else
  echo "==> Pulling OnlyOffice image..."
  docker pull "${ONLYOFFICE_SOURCE_IMAGE}"
fi

echo "==> Retagging OnlyOffice image..."
docker tag "${ONLYOFFICE_SOURCE_IMAGE}" "${ONLYOFFICE_IMAGE}"

rm -f "${IMAGE_TAR}"

echo "==> Exporting image bundle..."
docker save -o "${IMAGE_TAR}" \
  "${WEB_IMAGE}" \
  "${FASTAPI_IMAGE}" \
  "${OPENCODE_IMAGE}" \
  "${ONLYOFFICE_IMAGE}"

cp "${REPO_ROOT}/docker-compose.yml" "${BUNDLE_DIR}/docker-compose.yml"
cp "${REPO_ROOT}/docker-compose.airgap.yml" "${BUNDLE_DIR}/docker-compose.airgap.yml"
cp "${REPO_ROOT}/.env.airgap.example" "${BUNDLE_DIR}/.env.airgap.example"
cp "${REPO_ROOT}/scripts/load-airgap-images.sh" "${BUNDLE_DIR}/load-airgap-images.sh"
cp "${REPO_ROOT}/scripts/up-airgap.sh" "${BUNDLE_DIR}/up-airgap.sh"

cat > "${MANIFEST_PATH}" <<EOF
{
  "createdAt": "$(date +%Y-%m-%dT%H:%M:%S)",
  "bundleFile": "$(basename "${IMAGE_TAR}")",
  "images": [
    "${WEB_IMAGE}",
    "${FASTAPI_IMAGE}",
    "${OPENCODE_IMAGE}",
    "${ONLYOFFICE_IMAGE}"
  ],
  "composeFiles": [
    "docker-compose.yml",
    "docker-compose.airgap.yml"
  ],
  "envTemplate": ".env.airgap.example"
}
EOF

echo
echo "Air-gapped bundle is ready:"
echo "  Bundle dir : ${BUNDLE_DIR}"
echo "  Image tar  : ${IMAGE_TAR}"
echo "  Env sample : ${BUNDLE_DIR}/.env.airgap.example"
