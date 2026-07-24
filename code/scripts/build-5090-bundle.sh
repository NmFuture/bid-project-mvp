#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DEPLOY_TARGET=5090
export INCLUDE_OCR=true

exec "${SCRIPT_DIR}/build-airgap-bundle.sh" "$@"
