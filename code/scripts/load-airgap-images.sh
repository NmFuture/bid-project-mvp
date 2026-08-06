#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

IMAGE_TAR="${1:-}"
if [[ -n "${IMAGE_TAR}" ]]; then
  if [[ ! -f "${IMAGE_TAR}" ]]; then
    echo "Cannot find the requested offline image tar: ${IMAGE_TAR}" >&2
    exit 1
  fi
  IMAGE_TAR="$(cd "$(dirname "${IMAGE_TAR}")" && pwd)/$(basename "${IMAGE_TAR}")"
  BUNDLE_ROOT="$(cd "$(dirname "${IMAGE_TAR}")/.." && pwd)"
elif [[ -f "${ROOT_DIR}/bundle-manifest.json" ]]; then
  BUNDLE_ROOT="${ROOT_DIR}"
elif [[ -f "${ROOT_DIR}/offline-dist/bundle-manifest.json" ]]; then
  BUNDLE_ROOT="${ROOT_DIR}/offline-dist"
else
  echo "Cannot find bundle-manifest.json in the standard bundle location." >&2
  echo "Pass the tar inside a complete release bundle explicitly." >&2
  exit 1
fi

MANIFEST_PATH="${BUNDLE_ROOT}/bundle-manifest.json"
CHECKSUM_PATH="${BUNDLE_ROOT}/SHA256SUMS"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to verify the offline bundle manifest." >&2
  exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
  CHECKSUM_COMMAND=(sha256sum -c)
elif command -v shasum >/dev/null 2>&1; then
  CHECKSUM_COMMAND=(shasum -a 256 -c)
else
  echo "sha256sum or shasum is required to verify the offline bundle." >&2
  exit 1
fi

for required_file in "${MANIFEST_PATH}" "${CHECKSUM_PATH}"; do
  if [[ ! -f "${required_file}" ]]; then
    echo "Incomplete offline bundle; missing ${required_file}." >&2
    exit 1
  fi
done

CHECKSUM_INPUT_PATH="$(mktemp "${TMPDIR:-/tmp}/sewpg-airgap-checksums.XXXXXX")"
cleanup() {
  rm -f "${CHECKSUM_INPUT_PATH}"
}
trap cleanup EXIT
tr -d '\r' < "${CHECKSUM_PATH}" > "${CHECKSUM_INPUT_PATH}"

if ! manifest_values="$(python3 -c '
import json
import pathlib
import re
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    manifest = json.load(stream)

bundle_file = manifest.get("bundleFile")
image_id = manifest.get("onlyofficeImageId")
images = manifest.get("images")
if not isinstance(bundle_file, str) or pathlib.Path(bundle_file).name != bundle_file:
    raise SystemExit("bundleFile must be a plain filename")
if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
    raise SystemExit("onlyofficeImageId is missing or invalid")
if not isinstance(images, list):
    raise SystemExit("images must be a list")
onlyoffice_images = [
    image for image in images
    if isinstance(image, str) and image.startswith("sewpg-bid/onlyoffice:")
]
if len(onlyoffice_images) != 1:
    raise SystemExit("manifest must contain exactly one project OnlyOffice image")
print("\t".join((bundle_file, image_id, onlyoffice_images[0])))
' "${MANIFEST_PATH}")"; then
  echo "Invalid offline bundle manifest: ${MANIFEST_PATH}" >&2
  exit 1
fi
IFS=$'\t' read -r MANIFEST_BUNDLE_FILE EXPECTED_ONLYOFFICE_ID ONLYOFFICE_IMAGE \
  <<< "${manifest_values}"

EXPECTED_IMAGE_TAR="${BUNDLE_ROOT}/images/${MANIFEST_BUNDLE_FILE}"
if [[ ! -f "${EXPECTED_IMAGE_TAR}" ]]; then
  echo "Bundle image tar declared by the manifest is missing: ${EXPECTED_IMAGE_TAR}" >&2
  exit 1
fi
EXPECTED_IMAGE_TAR="$(cd "$(dirname "${EXPECTED_IMAGE_TAR}")" && pwd)/$(basename "${EXPECTED_IMAGE_TAR}")"
if [[ -n "${IMAGE_TAR}" && "${IMAGE_TAR}" != "${EXPECTED_IMAGE_TAR}" ]]; then
  echo "Requested tar does not match bundle-manifest.json." >&2
  echo "Expected: ${EXPECTED_IMAGE_TAR}" >&2
  echo "Actual:   ${IMAGE_TAR}" >&2
  exit 1
fi
IMAGE_TAR="${EXPECTED_IMAGE_TAR}"

for checksummed_file in "bundle-manifest.json" "images/${MANIFEST_BUNDLE_FILE}"; do
  if ! awk -v expected="${checksummed_file}" \
    '{sub(/\r$/, "")} length($1) == 64 && substr($0, 67) == expected {found = 1} END {exit !found}' \
    "${CHECKSUM_INPUT_PATH}"; then
    echo "Offline checksum list does not cover ${checksummed_file}." >&2
    exit 1
  fi
done

echo "==> Verifying offline bundle checksums..."
(cd "${BUNDLE_ROOT}" && "${CHECKSUM_COMMAND[@]}" "${CHECKSUM_INPUT_PATH}")

docker load -i "${IMAGE_TAR}"

ACTUAL_ONLYOFFICE_ID="$(docker image inspect --format '{{.Id}}' "${ONLYOFFICE_IMAGE}")"
if [[ "${ACTUAL_ONLYOFFICE_ID}" != "${EXPECTED_ONLYOFFICE_ID}" ]]; then
  echo "OnlyOffice image ID mismatch after docker load." >&2
  echo "Expected: ${EXPECTED_ONLYOFFICE_ID}" >&2
  echo "Actual:   ${ACTUAL_ONLYOFFICE_ID}" >&2
  exit 1
fi
echo "OnlyOffice image verified: ${ONLYOFFICE_IMAGE} (${ACTUAL_ONLYOFFICE_ID})"
