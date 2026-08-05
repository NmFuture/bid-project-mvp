#!/usr/bin/env bash

readonly ONLYOFFICE_DEV_IMAGE_DEFAULT="sewpg-bid/onlyoffice:dev-fontpack-v1"

configure_compose_build_compat_args() {
  COMPOSE_BUILD_PROVENANCE_ARG=""

  local compose_build_help
  if compose_build_help="$(docker compose build --help 2>&1)" && \
    grep -q -- '--provenance' <<< "${compose_build_help}"; then
    COMPOSE_BUILD_PROVENANCE_ARG="--provenance=false"
    return 0
  fi

  echo "Warning: docker compose build does not support --provenance; continuing without disabling provenance." >&2
  echo "Image IDs may vary across builds. Upgrade Docker Compose to 2.39 or newer to disable provenance." >&2
}

onlyoffice_image_from_env_template() {
  local env_file="$1"

  awk -F= '$1 == "ONLYOFFICE_IMAGE" {
    sub(/^[^=]*=/, "")
    sub(/\r$/, "")
    print
    exit
  }' "${env_file}"
}

require_expected_onlyoffice_image() {
  local env_file="$1"
  local expected_image="$2"
  local migration_instruction="$3"
  shift 3

  if [[ -z "${expected_image}" ]]; then
    echo "Cannot determine the expected OnlyOffice image for ${env_file}." >&2
    return 1
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to validate the OnlyOffice image policy." >&2
    return 1
  fi

  local compose_config
  if ! compose_config="$(docker compose "$@" config --format json)"; then
    echo "Unable to resolve the effective OnlyOffice image from Compose configuration." >&2
    return 1
  fi

  local actual_image
  if ! actual_image="$(python3 -c '
import json
import sys

config = json.load(sys.stdin)
image = config.get("services", {}).get("onlyoffice", {}).get("image")
if not isinstance(image, str) or not image:
    raise SystemExit("services.onlyoffice.image is missing")
print(image)
' <<< "${compose_config}")"; then
    echo "Unable to read services.onlyoffice.image from Compose configuration." >&2
    return 1
  fi

  if [[ "${actual_image}" == "${expected_image}" ]]; then
    return 0
  fi

  cat >&2 <<EOF
Unexpected OnlyOffice image configuration.

Expected: ${expected_image}
Actual:   ${actual_image}

The effective Compose configuration does not use the image assigned to this
development or release context. It may lack the project font contract and
entrypoint, or point at image contents that cannot be traced to this release.

Update ${env_file}:
  ${migration_instruction}

For an air-gapped deployment, import the matching release bundle before retrying.
EOF
  return 1
}
