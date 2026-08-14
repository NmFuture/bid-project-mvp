#!/usr/bin/env bash
# cleanup-opencode-data.sh — opencode_data 卷清理（B3 / engine-05，对应 harness-04）
#
# 背景：
#   opencode 容器把会话数据持久化在命名卷 opencode_data（容器内
#   /root/.local/share/opencode）。B3 起后端会在任务终态主动 DELETE 会话
#   （agent_engine/orchestrator.py 的 _recycle_session），但仍有残留来源：
#   服务重启/容器重建时未走到终态的会话、刻意保留的技术标共创对话多轮会话
#   （technical_chat_service，keep_session=True）。本脚本是兜底清理，消除卷的
#   无限增长；compose 默认行为不变（不挂自动清理 sidecar）。
#
# 清理策略：
#   - 按文件 mtime 清理 N 天前的数据，N 由 OPENCODE_DATA_RETENTION_DAYS 配置，
#     默认 7 天（保守值，排障留痕窗口足够）。
#   - 进行中的会话文件 mtime 会持续刷新，不会被误删；超窗的多轮对话会话被清后，
#     前端已有「会话已失效，请新建对话」的降级路径。
#   - 默认 dry-run（只列出将删除的文件数与体积），--apply 才真正删除。
#
# 触发方式：
#   - 手动：code/scripts/cleanup-opencode-data.sh [--apply]（需 opencode 容器在运行）。
#   - 定时：cron 示例（每天凌晨 dry-run 转 apply）：
#       17 3 * * * /path/to/repo/code/scripts/cleanup-opencode-data.sh --apply >> /var/log/opencode-data-cleanup.log 2>&1
#   - 5090/气隙部署同样适用（同一 compose 服务名 opencode）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  ROOT_DIR="${SCRIPT_DIR}"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

RETENTION_DAYS="${OPENCODE_DATA_RETENTION_DAYS:-7}"
ACTION="${1:---dry-run}"
DATA_DIR="/root/.local/share/opencode"

case "${ACTION}" in
  --dry-run)
    DELETE=0
    ;;
  --apply)
    DELETE=1
    ;;
  *)
    echo "用法: $0 [--dry-run|--apply]" >&2
    echo "  --dry-run（默认）只统计将清理的内容；--apply 真正删除。" >&2
    exit 1
    ;;
esac

case "${RETENTION_DAYS}" in
  ''|*[!0-9]*)
    echo "OPENCODE_DATA_RETENTION_DAYS 必须是非负整数，当前: ${RETENTION_DAYS}" >&2
    exit 1
    ;;
esac

if ! docker compose --project-directory "${ROOT_DIR}" -f "${ROOT_DIR}/docker-compose.yml" ps --status running --services 2>/dev/null | grep -qx opencode; then
  echo "opencode 容器未在运行，无法清理卷内数据。先 docker compose up -d opencode。" >&2
  exit 1
fi

compose_exec() {
  docker compose --project-directory "${ROOT_DIR}" -f "${ROOT_DIR}/docker-compose.yml" exec -T opencode "$@"
}

echo "opencode_data 清理：保留窗口 ${RETENTION_DAYS} 天，模式 $([[ ${DELETE} -eq 1 ]] && echo apply || echo dry-run)。"
# 显式捕获 find 失败：dry-run 也不能静默吞错（此前 2>/dev/null 会把扫描失败
# 误报成「0 个文件」）。命令替换保留 find 的 stderr 输出，失败即报错退出。
SCAN_OUTPUT="$(compose_exec find "${DATA_DIR}" -xdev -type f -mtime "+${RETENTION_DAYS}" -printf '%s\n')" || {
  echo "扫描 ${DATA_DIR} 失败（find 返回非零），中止；请检查 opencode 容器与卷状态。" >&2
  exit 1
}
printf '%s' "${SCAN_OUTPUT}" \
  | awk '{files += 1; bytes += $1} END {printf "待清理：%d 个文件，共 %.1f MiB。\n", files, bytes / 1048576}'

if [[ "${DELETE}" -eq 1 ]]; then
  compose_exec find "${DATA_DIR}" -xdev -type f -mtime "+${RETENTION_DAYS}" -delete
  # 清掉删空后的目录（保留卷根）。
  compose_exec find "${DATA_DIR}" -xdev -mindepth 1 -type d -empty -delete
  echo "清理完成。"
else
  echo "dry-run：未删除任何内容。确认后加 --apply 执行。"
fi
