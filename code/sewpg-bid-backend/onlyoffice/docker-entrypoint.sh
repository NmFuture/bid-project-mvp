#!/usr/bin/env bash
set -euo pipefail

max_download_bytes="${ONLYOFFICE_MAX_DOWNLOAD_BYTES:-524288000}"
tempfile_upload_bytes="${ONLYOFFICE_TEMPFILE_UPLOAD_LIMIT_BYTES:-${max_download_bytes}}"
image_size_bytes="${ONLYOFFICE_IMAGE_SIZE_LIMIT_BYTES:-52428800}"
download_timeout="${ONLYOFFICE_DOWNLOAD_TIMEOUT:-10m}"
nginx_body_size="${ONLYOFFICE_NGINX_CLIENT_MAX_BODY_SIZE:-512m}"

python3 - <<'PY'
import json
import os
from pathlib import Path

config_path = Path("/etc/onlyoffice/documentserver/local.json")
data = json.loads(config_path.read_text(encoding="utf-8"))


def ensure_object(path: list[str]) -> dict:
    current = data
    for key in path:
        value = current.setdefault(key, {})
        if not isinstance(value, dict):
            value = {}
            current[key] = value
        current = value
    return current


server = ensure_object(["services", "CoAuthoring", "server"])
server["limits_tempfile_upload"] = int(os.environ["ONLYOFFICE_TEMPFILE_UPLOAD_LIMIT_BYTES"])
server["limits_image_size"] = int(os.environ["ONLYOFFICE_IMAGE_SIZE_LIMIT_BYTES"])

converter = ensure_object(["FileConverter", "converter"])
converter["maxDownloadBytes"] = int(os.environ["ONLYOFFICE_MAX_DOWNLOAD_BYTES"])
converter["downloadTimeout"] = {
    "connectionAndInactivity": os.environ["ONLYOFFICE_DOWNLOAD_TIMEOUT"],
    "wholeCycle": os.environ["ONLYOFFICE_DOWNLOAD_TIMEOUT"],
}

config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if [ -f /etc/onlyoffice/documentserver/nginx/includes/ds-common.conf ]; then
  sed -i "s/client_max_body_size .*/client_max_body_size ${nginx_body_size};/" \
    /etc/onlyoffice/documentserver/nginx/includes/ds-common.conf
fi

fc-cache -f
/usr/local/bin/sewpg-verify-fonts
if command -v documentserver-generate-allfonts.sh >/dev/null 2>&1; then
  documentserver-generate-allfonts.sh
fi

exec /app/ds/run-document-server.sh "$@"
