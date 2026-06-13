#!/bin/sh
set -eu

OPENCODE_HOME_DIR="${OPENCODE_HOME:-/root/.local/share/opencode}"
mkdir -p "${OPENCODE_HOME_DIR}"

if [ -f /bootstrap/opencode-host/auth.json ]; then
  cp /bootstrap/opencode-host/auth.json "${OPENCODE_HOME_DIR}/auth.json"
fi

RUNTIME_CONFIG_PATH="${OPENCODE_RUNTIME_CONFIG_PATH:-/data/documents/_runtime/opencode/opencode.runtime.json}"
EFFECTIVE_CONFIG_PATH="/workspace/opencode.effective.json"

write_effective_config() {
  python3 - "$1" "${EFFECTIVE_CONFIG_PATH}" <<'PY'
import json
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])

config = json.loads(source_path.read_text(encoding="utf-8"))
permission = config.get("permission")
if not isinstance(permission, dict):
    permission = {}
    config["permission"] = permission
external_directory = permission.get("external_directory")
if not isinstance(external_directory, dict):
    external_directory = {}
    permission["external_directory"] = external_directory
external_directory.update({
    "/data/parsed/**": "allow",
    "/data/documents/**": "allow",
    "/data/uploads/**": "allow",
    "/tmp/**": "allow",
})
target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

if [ -f "${RUNTIME_CONFIG_PATH}" ]; then
  write_effective_config "${RUNTIME_CONFIG_PATH}"
  export OPENCODE_CONFIG="${EFFECTIVE_CONFIG_PATH}"
elif [ -n "${INTERNAL_LLM_BASE_URL:-}" ]; then
  python3 - <<'PY'
import json
import os
from pathlib import Path

provider_id = os.getenv("OPENCODE_PROVIDER_ID", "internal-openai")
model_id = os.getenv("OPENCODE_MODEL_ID", "internal-model")

config = {
    "$schema": "https://opencode.ai/config.json",
    "autoupdate": False,
    "share": "disabled",
    "model": f"{provider_id}/{model_id}",
    "provider": {
        provider_id: {
            "npm": "@ai-sdk/openai-compatible",
            "name": os.getenv("INTERNAL_LLM_PROVIDER_NAME", "Internal LLM Gateway"),
            "options": {
                "baseURL": os.getenv("INTERNAL_LLM_BASE_URL", "").rstrip("/"),
            },
            "models": {
                model_id: {
                    "name": os.getenv("INTERNAL_LLM_MODEL_LABEL", model_id),
                }
            },
        }
    },
    "permission": {
        "skill": {
            "*": "allow",
        },
        "bash": "allow",
        "external_directory": {
            "/data/parsed/**": "allow",
            "/data/documents/**": "allow",
            "/data/uploads/**": "allow",
            "/tmp/**": "allow",
        },
        "task": "deny",
        "read": "deny",
        "edit": "deny",
    },
}

api_key = os.getenv("INTERNAL_LLM_API_KEY", "")
if api_key:
    config["provider"][provider_id]["options"]["apiKey"] = api_key

headers_json = os.getenv("INTERNAL_LLM_HEADERS_JSON", "").strip()
if headers_json:
    try:
        parsed_headers = json.loads(headers_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"INTERNAL_LLM_HEADERS_JSON is not valid JSON: {exc}") from exc
    if parsed_headers:
        config["provider"][provider_id]["options"]["headers"] = parsed_headers

config_path = Path("/workspace/opencode.runtime.json")
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  export OPENCODE_CONFIG=/workspace/opencode.runtime.json
else
  export OPENCODE_CONFIG=/workspace/opencode.json
fi

exec "$@"
