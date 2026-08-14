#!/bin/sh
set -eu

OPENCODE_HOME_DIR="${OPENCODE_HOME:-/root/.local/share/opencode}"
mkdir -p "${OPENCODE_HOME_DIR}"

if [ -f /bootstrap/opencode-host/auth.json ]; then
  cp /bootstrap/opencode-host/auth.json "${OPENCODE_HOME_DIR}/auth.json"
fi

RUNTIME_CONFIG_PATH="${OPENCODE_RUNTIME_CONFIG_PATH:-/data/documents/_runtime/opencode/opencode.runtime.json}"
WORKSPACE_DIR="${OPENCODE_WORKSPACE_DIR:-/workspace}"
export WORKSPACE_DIR
EFFECTIVE_CONFIG_PATH="${WORKSPACE_DIR}/opencode.effective.json"

# harness-08（模型回退单点化）：provider/model 归一化（big-pickle →
# deepseek/deepseek-v4-flash、provider 前缀剥离、空值回退默认）在本脚本内的
# 唯一事实源。runtime.json 改写 / INTERNAL_LLM / legacy 三个分支统一调用本函数；
# Python 侧 app/core/config.py 的 normalize_opencode_model_selection 与本函数
# 互为镜像，改动必须同步（config.py 内有对应注释）。
resolve_model_selection() {
  # 入参：$1=provider_id（可空）$2=model_id（可空）；输出："<provider> <model>"（空格分隔）
  python3 - "${1:-}" "${2:-}" <<'PY'
import sys

DEFAULT_PROVIDER_ID = "deepseek"
DEFAULT_MODEL_ID = "deepseek-v4-flash"

provider_id = (sys.argv[1] or "").strip() or DEFAULT_PROVIDER_ID
model_id = (sys.argv[2] or "").strip() or DEFAULT_MODEL_ID

if (provider_id, model_id) == ("opencode", "big-pickle") or model_id == "opencode/big-pickle":
    provider_id, model_id = DEFAULT_PROVIDER_ID, DEFAULT_MODEL_ID

if model_id == f"{DEFAULT_PROVIDER_ID}/{DEFAULT_MODEL_ID}":
    provider_id, model_id = DEFAULT_PROVIDER_ID, DEFAULT_MODEL_ID

qualified_prefix = f"{provider_id}/"
if model_id.startswith(qualified_prefix):
    model_id = model_id[len(qualified_prefix):].strip()

print(f"{provider_id} {model_id or DEFAULT_MODEL_ID}")
PY
}

write_effective_config() {
  # $1=源 runtime.json；$2=原始 model 串；$3/$4=经 resolve_model_selection 归一后的 provider/model
  python3 - "$1" "${EFFECTIVE_CONFIG_PATH}" "$2" "$3" "$4" <<'PY'
import json
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
raw_model = sys.argv[3].strip()
resolved_provider_id = sys.argv[4].strip()
resolved_model_id = sys.argv[5].strip()

config = json.loads(source_path.read_text(encoding="utf-8"))
resolved_model = f"{resolved_provider_id}/{resolved_model_id}"
if raw_model and raw_model != resolved_model:
    # 旧 runtime 配置的模型经统一映射后发生变化（如 opencode/big-pickle），
    # 同步改写 model 并迁移旧 provider 块
    config["model"] = resolved_model
    providers = config.get("provider")
    if isinstance(providers, dict):
        legacy_provider = providers.pop(raw_model.partition("/")[0], None)
        if isinstance(legacy_provider, dict):
            legacy_provider["name"] = resolved_provider_id
            legacy_provider["models"] = {
                resolved_model_id: {
                    "name": resolved_model_id,
                }
            }
            providers[resolved_provider_id] = legacy_provider
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

# harness-09（skill 运行时注册）：命令别名不再由 Dockerfile 构建期 printf 固化。
# 事实源是 skills/commands.json（随 skills 目录 COPY 进镜像）；每次容器启动由本函数
# 重新生成 BIN_DIR 下的 wrapper（含子命令白名单）。新增/调整别名只需改 commands.json，
# 未登记的命令不会生成 wrapper，白名单外的子命令在 wrapper 内拒绝（exit 64）。
register_skill_commands() {
  SKILLS_DIR="${OPENCODE_SKILLS_DIR:-${WORKSPACE_DIR}/.opencode/skills}" \
  BIN_DIR="${OPENCODE_SKILL_BIN_DIR:-/usr/local/bin}" \
  python3 - <<'PY'
import json
import os
import re
import sys
from pathlib import Path

skills_dir = Path(os.environ["SKILLS_DIR"]).resolve()
bin_dir = Path(os.environ["BIN_DIR"])
registry_path = skills_dir / "commands.json"
if not registry_path.is_file():
    raise SystemExit(f"skill 命令注册表不存在: {registry_path}")
try:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    raise SystemExit(f"skill 命令注册表不是合法 JSON: {exc}") from exc
commands = registry.get("commands")
if not isinstance(commands, list) or not commands:
    raise SystemExit(f"skill 命令注册表为空或缺少 commands 列表: {registry_path}")

NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
LITERAL_RE = re.compile(r"[A-Za-z0-9._/-]+")


def fail(message: str) -> None:
    raise SystemExit(f"skill 命令注册失败: {message}")


def render_literal(token: str) -> str:
    if not LITERAL_RE.fullmatch(token):
        fail(f"非法参数字面量: {token!r}")
    return f"'{token}'"


seen: set[str] = set()
bin_dir.mkdir(parents=True, exist_ok=True)
for entry in commands:
    if not isinstance(entry, dict):
        fail(f"注册项必须是对象: {entry!r}")
    name = entry.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        fail(f"非法命令名: {name!r}")
    if name in seen:
        fail(f"重复命令名: {name}")
    seen.add(name)

    script = entry.get("script")
    if not isinstance(script, str) or script.startswith("/") or ".." in Path(script).parts:
        fail(f"{name}: 非法 script 路径: {script!r}")
    script_path = skills_dir / script
    if not script_path.is_file():
        fail(f"{name}: script 不存在: {script_path}")

    usage = entry.get("usage")
    if not isinstance(usage, str) or not usage.strip() or "\n" in usage or "'" in usage:
        fail(f"{name}: 非法 usage（单行、不含单引号）")

    subcommands = entry.get("subcommands")
    argv = entry.get("argv")
    prefix_args = entry.get("prefix_args") or []
    if subcommands is not None and argv is not None:
        fail(f"{name}: subcommands 与 argv 互斥")
    if argv is not None and "{manifest}" not in argv:
        fail(f"{name}: argv 必须包含 {{manifest}} 占位符")

    if subcommands is not None:
        if not subcommands or any(not NAME_RE.fullmatch(str(item)) for item in subcommands):
            fail(f"{name}: 非法子命令白名单: {subcommands!r}")
        rendered_args = " ".join([f"'{script_path}'", *[render_literal(t) for t in prefix_args], '"$@"'])
        lines = [
            "#!/bin/sh",
            'case "$1" in',
            f"  {'|'.join(str(item) for item in subcommands)}) ;;",
            f"  *) echo 'usage: {usage}' >&2; exit 64 ;;",
            "esac",
            f"exec python3 {rendered_args}",
        ]
    elif argv is not None:
        rendered = ['"$1"' if token == "{manifest}" else render_literal(str(token)) for token in argv]
        lines = [
            "#!/bin/sh",
            'if [ "$#" -ne 1 ]; then',
            f"  echo 'usage: {usage}' >&2",
            "  exit 64",
            "fi",
            f"exec python3 '{script_path}' {' '.join(rendered)}",
        ]
    else:
        lines = [
            "#!/bin/sh",
            'if [ "$#" -lt 1 ]; then',
            f"  echo 'usage: {usage}' >&2",
            "  exit 64",
            "fi",
            f"exec python3 '{script_path}' \"$@\"",
        ]

    target = bin_dir / name
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.chmod(0o755)

print(f"skill commands registered ({len(seen)}): {' '.join(sorted(seen))}", file=sys.stderr)
PY
}

register_skill_commands

if [ -f "${RUNTIME_CONFIG_PATH}" ]; then
  raw_model="$(python3 -c 'import json, sys; print(str(json.loads(open(sys.argv[1], encoding="utf-8").read()).get("model") or ""))' "${RUNTIME_CONFIG_PATH}")"
  case "${raw_model}" in
    */*) raw_provider_id="${raw_model%%/*}"; raw_model_id="${raw_model#*/}" ;;
    *) raw_provider_id=""; raw_model_id="${raw_model}" ;;
  esac
  resolved_selection="$(resolve_model_selection "${raw_provider_id}" "${raw_model_id}")"
  write_effective_config "${RUNTIME_CONFIG_PATH}" "${raw_model}" "${resolved_selection%% *}" "${resolved_selection##* }"
  export OPENCODE_CONFIG="${EFFECTIVE_CONFIG_PATH}"
elif [ -n "${INTERNAL_LLM_BASE_URL:-}" ]; then
  resolved_selection="$(resolve_model_selection "${OPENCODE_PROVIDER_ID:-}" "${OPENCODE_MODEL_ID:-}")"
  RESOLVED_PROVIDER_ID="${resolved_selection%% *}" RESOLVED_MODEL_ID="${resolved_selection##* }" python3 - <<'PY'
import json
import os
from pathlib import Path

provider_id = os.environ["RESOLVED_PROVIDER_ID"]
model_id = os.environ["RESOLVED_MODEL_ID"]

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

config_path = Path(os.environ["WORKSPACE_DIR"]) / "opencode.runtime.json"
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  export OPENCODE_CONFIG="${WORKSPACE_DIR}/opencode.runtime.json"
else
  # 兼容回退：runtime 配置与 INTERNAL_LLM 均未配置时，基于 opencode.json 注入环境变量指定的默认模型。
  # opencode.json 本身不落 model：opencode 的项目目录配置优先级高于 OPENCODE_CONFIG，
  # 在 opencode.json 里写死 model 会覆盖 runtime 配置的模型，导致系统设置的模型重启后仍不生效。
  resolved_selection="$(resolve_model_selection "${OPENCODE_PROVIDER_ID:-}" "${OPENCODE_MODEL_ID:-}")"
  RESOLVED_PROVIDER_ID="${resolved_selection%% *}" RESOLVED_MODEL_ID="${resolved_selection##* }" python3 - <<'PY'
import json
import os
from pathlib import Path

provider_id = os.environ["RESOLVED_PROVIDER_ID"]
model_id = os.environ["RESOLVED_MODEL_ID"]

workspace = Path(os.environ["WORKSPACE_DIR"])
config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
config["model"] = f"{provider_id}/{model_id}"
config_path = workspace / "opencode.legacy.json"
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  export OPENCODE_CONFIG="${WORKSPACE_DIR}/opencode.legacy.json"
fi

exec "$@"
