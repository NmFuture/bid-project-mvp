#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${REPO_ROOT}/sewpg-bid-backend/onlyoffice/image-policy.sh"
BUNDLE_DIR="${1:-${REPO_ROOT}/offline-dist}"
TAG="${2:-offline-$(date +%Y%m%d%H%M)}"
ONLYOFFICE_SOURCE_IMAGE="${ONLYOFFICE_SOURCE_IMAGE:-onlyoffice/documentserver:9.3.1.2@sha256:0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31}"
ONLYOFFICE_FONT_BUILDER_SOURCE_IMAGE="${ONLYOFFICE_FONT_BUILDER_SOURCE_IMAGE:-debian:bookworm-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e}"
REDIS_SOURCE_IMAGE="${REDIS_SOURCE_IMAGE:-redis:7-alpine}"
POSTGRES_SOURCE_IMAGE="${POSTGRES_SOURCE_IMAGE:-pgvector/pgvector:pg16}"
MINIO_SOURCE_IMAGE="${MINIO_SOURCE_IMAGE:-minio/minio:RELEASE.2025-04-22T22-12-26Z}"
INCLUDE_OCR="${INCLUDE_OCR:-false}"
OCR_SOURCE_IMAGE="${OCR_SOURCE_IMAGE:-vllm/vllm-openai:unlimited-ocr}"
DEPLOY_TARGET="${DEPLOY_TARGET:-generic}"
GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
  echo "Refusing to build a release bundle from a dirty worktree." >&2
  echo "Commit or remove tracked and untracked changes before retrying." >&2
  exit 1
fi

compose_build_args=(-f "${REPO_ROOT}/docker-compose.yml")
if [[ "${DEPLOY_TARGET}" == "5090" ]]; then
  INCLUDE_OCR=true
  compose_build_args+=(
    -f "${REPO_ROOT}/docker-compose.ocr.yml"
    -f "${REPO_ROOT}/docker-compose.5090.yml"
  )
fi

mkdir -p "${BUNDLE_DIR}/images"

export APP_IMAGE_TAG="${TAG}"
export WEB_IMAGE="sewpg-bid/web:${TAG}"
export FASTAPI_IMAGE="sewpg-bid/fastapi:${TAG}"
export DOCLING_IMAGE="sewpg-bid/docling-worker:${TAG}"
export OPENCODE_IMAGE="sewpg-bid/opencode:${TAG}"
export ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:${TAG}-fontpack-v1"
export ONLYOFFICE_BASE_IMAGE="${ONLYOFFICE_SOURCE_IMAGE}"
export ONLYOFFICE_FONT_BUILDER_IMAGE="${ONLYOFFICE_FONT_BUILDER_SOURCE_IMAGE}"
export ONLYOFFICE_BUILD_REVISION="${GIT_SHA}"
export REDIS_IMAGE="${REDIS_SOURCE_IMAGE}"
export OCR_IMAGE="${OCR_SOURCE_IMAGE}"

IMAGE_TAR="${BUNDLE_DIR}/images/sewpg-bid-images-${TAG}.tar"
MANIFEST_PATH="${BUNDLE_DIR}/bundle-manifest.json"
CHECKSUM_PATH="${BUNDLE_DIR}/SHA256SUMS"

ensure_image() {
  local image_name="$1"
  local image_label="$2"

  if docker image inspect "${image_name}" >/dev/null 2>&1; then
    echo "==> Reusing local ${image_label} image..."
  else
    echo "==> Pulling ${image_label} image..."
    docker pull "${image_name}"
  fi
}

require_digest_reference() {
  case "$1" in
    *@sha256:*) ;;
    *)
      echo "${2} must be pinned by sha256 digest: $1" >&2
      exit 1
      ;;
  esac
}

require_digest_reference "${ONLYOFFICE_SOURCE_IMAGE}" "OnlyOffice base image"
require_digest_reference "${ONLYOFFICE_FONT_BUILDER_SOURCE_IMAGE}" "OnlyOffice font builder image"

echo "==> Building application and OnlyOffice font images..."
configure_compose_build_compat_args
docker compose "${compose_build_args[@]}" build \
  ${COMPOSE_BUILD_PROVENANCE_ARG:+"${COMPOSE_BUILD_PROVENANCE_ARG}"} \
  web fastapi docling-worker opencode onlyoffice
ensure_image "${REDIS_SOURCE_IMAGE}" "Redis"
ensure_image "${POSTGRES_SOURCE_IMAGE}" "PostgreSQL"
ensure_image "${MINIO_SOURCE_IMAGE}" "MinIO"

if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then
  ensure_image "${OCR_SOURCE_IMAGE}" "OCR vLLM"
fi

OCR_SOURCE_DIGEST=""
if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then
  OCR_SOURCE_DIGEST="$(docker image inspect --format '{{join .RepoDigests ","}}' "${OCR_SOURCE_IMAGE}" | cut -d, -f1)"
fi
ONLYOFFICE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${ONLYOFFICE_IMAGE}")"

rm -f "${IMAGE_TAR}"

echo "==> Exporting image bundle..."
save_images=(
  "${WEB_IMAGE}"
  "${FASTAPI_IMAGE}"
  "${DOCLING_IMAGE}"
  "${OPENCODE_IMAGE}"
  "${ONLYOFFICE_IMAGE}"
  "${REDIS_IMAGE}"
  "${POSTGRES_SOURCE_IMAGE}"
  "${MINIO_SOURCE_IMAGE}"
)
if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then
  save_images+=("${OCR_SOURCE_IMAGE}")
fi
docker save -o "${IMAGE_TAR}" "${save_images[@]}"

cp "${REPO_ROOT}/docker-compose.yml" "${BUNDLE_DIR}/docker-compose.yml"
cp "${REPO_ROOT}/docker-compose.airgap.yml" "${BUNDLE_DIR}/docker-compose.airgap.yml"
cp "${REPO_ROOT}/docker-compose.ocr.yml" "${BUNDLE_DIR}/docker-compose.ocr.yml"
cp "${REPO_ROOT}/docker-compose.ocr.airgap.yml" "${BUNDLE_DIR}/docker-compose.ocr.airgap.yml"
cp "${REPO_ROOT}/docker-compose.5090.yml" "${BUNDLE_DIR}/docker-compose.5090.yml"
awk -v tag="${TAG}" '
  /^APP_IMAGE_TAG=/ { print "APP_IMAGE_TAG=" tag; next }
  /^WEB_IMAGE=/ { print "WEB_IMAGE=sewpg-bid/web:" tag; next }
  /^FASTAPI_IMAGE=/ { print "FASTAPI_IMAGE=sewpg-bid/fastapi:" tag; next }
  /^DOCLING_IMAGE=/ { print "DOCLING_IMAGE=sewpg-bid/docling-worker:" tag; next }
  /^OPENCODE_IMAGE=/ { print "OPENCODE_IMAGE=sewpg-bid/opencode:" tag; next }
  /^ONLYOFFICE_IMAGE=/ { print "ONLYOFFICE_IMAGE=sewpg-bid/onlyoffice:" tag "-fontpack-v1"; next }
  { print }
' "${REPO_ROOT}/.env.airgap.example" > "${BUNDLE_DIR}/.env.airgap.example"
mkdir -p "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice"
cp -R "${REPO_ROOT}/sewpg-bid-backend/onlyoffice/." \
  "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice/"
chmod +x "${BUNDLE_DIR}/sewpg-bid-backend/onlyoffice/docker-entrypoint.sh"
mkdir -p "${BUNDLE_DIR}/initdb"
cp -R "${REPO_ROOT}/initdb/." "${BUNDLE_DIR}/initdb/"
cp "${REPO_ROOT}/scripts/load-airgap-images.sh" "${BUNDLE_DIR}/load-airgap-images.sh"
cp "${REPO_ROOT}/scripts/up-airgap.sh" "${BUNDLE_DIR}/up-airgap.sh"
cp "${REPO_ROOT}/scripts/up-ocr.sh" "${BUNDLE_DIR}/up-ocr.sh"
cp "${REPO_ROOT}/scripts/up-5090.sh" "${BUNDLE_DIR}/up-5090.sh"

cat > "${MANIFEST_PATH}" <<EOF
{
  "createdAt": "$(date +%Y-%m-%dT%H:%M:%S)",
  "deployTarget": "${DEPLOY_TARGET}",
  "gitSha": "${GIT_SHA}",
  "onlyofficeImageId": "${ONLYOFFICE_IMAGE_ID}",
  "ocrSourceDigest": "${OCR_SOURCE_DIGEST}",
  "bundleFile": "$(basename "${IMAGE_TAR}")",
  "images": [
    "${WEB_IMAGE}",
    "${FASTAPI_IMAGE}",
    "${DOCLING_IMAGE}",
    "${OPENCODE_IMAGE}",
    "${ONLYOFFICE_IMAGE}",
    "${REDIS_IMAGE}",
    "${POSTGRES_SOURCE_IMAGE}",
    "${MINIO_SOURCE_IMAGE}"$(if [[ "${INCLUDE_OCR}" == "1" || "${INCLUDE_OCR}" == "true" || "${INCLUDE_OCR}" == "yes" ]]; then printf ',\n    "%s"' "${OCR_SOURCE_IMAGE}"; fi)
  ],
  "composeFiles": [
    "docker-compose.yml",
    "docker-compose.airgap.yml",
    "docker-compose.ocr.yml",
    "docker-compose.ocr.airgap.yml",
    "docker-compose.5090.yml"
  ],
  "envTemplate": ".env.airgap.example"
}
EOF

printf '%s\n' "${GIT_SHA}" > "${BUNDLE_DIR}/MAIN_SHA"
(
  cd "${BUNDLE_DIR}"
  {
    printf '%s\0' \
      "bundle-manifest.json" \
      "MAIN_SHA" \
      "images/$(basename "${IMAGE_TAR}")" \
      "docker-compose.yml" \
      "docker-compose.airgap.yml" \
      "docker-compose.ocr.yml" \
      "docker-compose.ocr.airgap.yml" \
      "docker-compose.5090.yml" \
      ".env.airgap.example" \
      "load-airgap-images.sh" \
      "up-airgap.sh" \
      "up-ocr.sh" \
      "up-5090.sh"
    find initdb sewpg-bid-backend/onlyoffice -type f -print0
  } | sort -z | xargs -0 sha256sum > "${CHECKSUM_PATH}"
)

echo
echo "Air-gapped bundle is ready:"
echo "  Bundle dir : ${BUNDLE_DIR}"
echo "  Image tar  : ${IMAGE_TAR}"
echo "  Env sample : ${BUNDLE_DIR}/.env.airgap.example"
echo "  Git SHA    : ${GIT_SHA}"
echo "  Checksums  : ${CHECKSUM_PATH}"
