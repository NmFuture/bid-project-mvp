#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

./start-local.sh "$@"
status=$?

echo
if [[ "${status}" -eq 0 ]]; then
  echo "Local product startup completed."
  echo "Open http://127.0.0.1/ in your browser."
else
  echo "Local product startup failed with exit code ${status}."
fi
echo "Press Enter to close this window."
read -r _

exit "${status}"
