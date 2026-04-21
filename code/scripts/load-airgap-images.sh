#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

DEFAULT_TAR=""
if compgen -G "${ROOT_DIR}/images/sewpg-bid-images-*.tar" > /dev/null; then
  DEFAULT_TAR="$(ls -1 "${ROOT_DIR}"/images/sewpg-bid-images-*.tar | head -n 1)"
elif compgen -G "${ROOT_DIR}/offline-dist/images/sewpg-bid-images-*.tar" > /dev/null; then
  DEFAULT_TAR="$(ls -1 "${ROOT_DIR}"/offline-dist/images/sewpg-bid-images-*.tar | head -n 1)"
fi

IMAGE_TAR="${1:-${DEFAULT_TAR}}"

if [[ -z "${IMAGE_TAR}" || ! -f "${IMAGE_TAR}" ]]; then
  echo "Cannot find an offline image tar. Pass it explicitly, for example:" >&2
  echo "  ./load-airgap-images.sh /path/to/sewpg-bid-images-offline-YYYYMMDDHHMM.tar" >&2
  exit 1
fi

docker load -i "${IMAGE_TAR}"
