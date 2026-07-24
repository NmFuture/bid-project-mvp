#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

./start-ocr.sh "$@"
status=$?

echo
if [[ "${status}" -eq 0 ]]; then
  echo "Local OCR startup completed."
else
  echo "Local OCR startup failed with exit code ${status}."
fi
echo "Press Enter to close this window."
read -r _

exit "${status}"
