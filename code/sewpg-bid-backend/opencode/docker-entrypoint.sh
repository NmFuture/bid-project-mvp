#!/bin/sh
set -eu

OPENCODE_HOME_DIR="${OPENCODE_HOME:-/root/.local/share/opencode}"
mkdir -p "${OPENCODE_HOME_DIR}"

if [ -f /bootstrap/opencode-host/auth.json ]; then
  cp /bootstrap/opencode-host/auth.json "${OPENCODE_HOME_DIR}/auth.json"
fi

RUNTIME_CONFIG_PATH="${OPENCODE_RUNTIME_CONFIG_PATH:-/data/documents/_runtime/opencode/opencode.runtime.json}"

if [ -f "${RUNTIME_CONFIG_PATH}" ]; then
  export OPENCODE_CONFIG="${RUNTIME_CONFIG_PATH}"
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
