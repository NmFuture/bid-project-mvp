#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# pre-run-check.sh — bid-project-mvp 本地运行预检
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 用法：
#   ./start_checklist/pre-run-check.sh              # 运行预检 / 读缓存
#   ./start_checklist/pre-run-check.sh --force       # 忽略缓存，强制重检
#   ./start_checklist/pre-run-check.sh --status       # 只看当前打勾状态
#
# 模型：会话首检 + 打勾持久化
#   - 第一次（或缓存过期）运行时逐项校验，通过的自动打勾
#   - 结果持久化到 start_checklist/.checked.local.json
#   - 下次运行若缓存命中且未过期 → 静默放行
#
# 缓存失效（触发重新检查）条件：
#   1.   强制 --force
#   2.    当前 HEAD commit 与打勾时记录不同（pull/rebase/checkout）
#   3.    code/ 下任意文件 mtime 晚于上一次 check 时间
#   4.    code/.env 内容 mtime/hash 发生变化
#   5.    距离 lastCheck 超过 maxStaleDays（默认 7 天）
#
# 退出码：
#   0 → 全部通过（或缓存命中）  1 → 有必检项未通过（阻断运行）
#
# 兼容性：bash 3.2+（原生支持 macOS 自带 bash）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -uo pipefail

# ── 路径 ──────────────────────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKLIST_YAML="$ROOT/start_checklist/pre-run-checklist.yaml"
CHECKED_FILE="$ROOT/start_checklist/.checked.local.json"
yaml_value() { # yaml_value <key> <default>
  local key="$1" default="$2" value=""
  [ -f "$CHECKLIST_YAML" ] && value=$(sed -n "s/^[[:space:]]*${key}:[[:space:]]*[\"']\\{0,1\\}\\([^\"'#]*\\)[\"']\\{0,1\\}[[:space:]]*\\(#.*\\)\\{0,1\\}$/\\1/p" "$CHECKLIST_YAML" | head -1 | sed 's/[[:space:]]*$//')
  if [ -n "$value" ]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$default"
  fi
}

TARGET_BRANCH="$(yaml_value syncBranch origin/main)"
MAX_STALE_DAYS="$(yaml_value maxStaleDays 7)"

# ── 参数 ──────────────────────────────────────────────────────
FORCE=false
STATUS_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --force)     FORCE=true ;;
    --status)    STATUS_ONLY=true ;;
    -h|--help)
      sed -n '1,/^set -uo/p' "$0" | grep -E '^#' | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# ── 计数器 ────────────────────────────────────────────────────
PASS=0; WARN=0; FAIL=0; SKIP=0

# 结果存到独立变量，避免关联数组：
#   RESULT_<id>     = "st|msg"  例 RESULT_code-version="ok|一致"
RESULT_code_version=""
RESULT_workspace=""
RESULT_deps_backend=""
RESULT_deps_frontend=""
RESULT_config=""
RESULT_secrets=""
RESULT_data=""

set_result() { # set_result <id> <st> <msg>
  local id="$1" st="$2"; shift 2
  local msg="$*"
  local var="RESULT_${id//-/_}"
  # 用 printf -v 赋值动态变量名（bash 3.2 安全）
  printf -v "$var" '%s' "${st}|${msg}"
}

get_result() { # get_result <id>  输出 "st|msg"
  local id="$1"
  local var="RESULT_${id//-/_}"
  echo "${!var}"
}

report() { # report <ok|warn|fail|skip> <check_id> <check_name> <msg>
  local st="$1" id="$2" name="$3"; shift 3
  local msg="$*"
  local icon
  case "$st" in
    ok)   icon="✅"; PASS=$((PASS+1));;
    warn) icon="⚠️ "; WARN=$((WARN+1));;
    fail) icon="❌"; FAIL=$((FAIL+1));;
    skip) icon="⏭️ "; SKIP=$((SKIP+1));;
  esac
  printf "  %s [%s] %s\n" "$icon" "$name" "$msg"
  set_result "$id" "$st" "$msg"
}

# ── 时间工具 ───────────────────────────────────────────────────
now_iso() { date +"%Y-%m-%dT%H:%M:%SZ"; }

days_since() {
  # macOS / BSD date — 计算距今多少天
  local target_s now_s
  target_s=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s 2>/dev/null) || { echo 999; return; }
  now_s=$(date +%s)
  echo $(( (now_s - target_s) / 86400 ))
}

hours_since() {
  local target_s now_s
  target_s=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s 2>/dev/null) || { echo 999; return; }
  now_s=$(date +%s)
  echo $(( (now_s - target_s) / 3600 ))
}

# ── 缓存读取 ───────────────────────────────────────────────────
CACHED_LASTCHECK=""
CACHED_HEAD=""
CACHED_REQUIRED_OK=false

cache_check_status() { # cache_check_status <id>
  local id="$1"
  sed -n "s/.*\"$id\"[[:space:]]*:[[:space:]]*{[[:space:]]*\"status\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$CHECKED_FILE" | head -1
}

load_cache() {
  [ -f "$CHECKED_FILE" ] || return 1
  CACHED_LASTCHECK=$(sed -n 's/.*"lastCheck"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CHECKED_FILE" | head -1)
  CACHED_HEAD=$(sed -n 's/.*"headAtCheck"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CHECKED_FILE" | head -1)
  if [ "$(cache_check_status code-version)" = "ok" ] && [ "$(cache_check_status config)" = "ok" ]; then
    CACHED_REQUIRED_OK=true
  else
    CACHED_REQUIRED_OK=false
  fi
  [ -n "$CACHED_LASTCHECK" ] && [ "$CACHED_LASTCHECK" != "null" ]
}

# ── 缓存失效判定 ───────────────────────────────────────────────
CACHE_INVALID_REASON=""
cache_valid() {
  $FORCE && { CACHE_INVALID_REASON="强制 --force"; return 1; }

  local current_head
  current_head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)
  $CACHED_REQUIRED_OK || { CACHE_INVALID_REASON="上次预检存在必检项未通过"; return 1; }
  [ "$current_head" != "$CACHED_HEAD" ] && {
    CACHE_INVALID_REASON="代码版本变更 (${CACHED_HEAD:0:8} → ${current_head:0:8})"
    return 1
  }

  # code/ 下关键目录是否有文件 mtime 晚于 .checked.local.json
  local lastcheck_s
  lastcheck_s=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$CACHED_LASTCHECK" +%s 2>/dev/null) || lastcheck_s=""
  if [ -n "$lastcheck_s" ]; then
    local newer
    newer=$(find "$ROOT/code/sewpg-bid-backend" "$ROOT/code/sewpg-bid-frontend" \
      -type d \( -name node_modules -o -name .venv -o -name dist -o -name __pycache__ -o -name .vite \) -prune -o \
      -type f -newer "$CHECKED_FILE" -print 2>/dev/null | head -1)
    [ -n "$newer" ] && { CACHE_INVALID_REASON="code/ 自上次预检后发生变更"; return 1; }
  fi

  # .env mtime 晚于 check 文件
  if [ -f "$ROOT/code/.env" ]; then
    local env_newer
    env_newer=$(find "$ROOT/code/.env" -newer "$CHECKED_FILE" -print 2>/dev/null | head -1)
    [ -n "$env_newer" ] && { CACHE_INVALID_REASON="code/.env 自上次预检后发生变更"; return 1; }
  fi

  # 超过 maxStaleDays
  local age
  age=$(days_since "$CACHED_LASTCHECK")
  [ "$age" -ge "$MAX_STALE_DAYS" ] && { CACHE_INVALID_REASON="距今 ${age} 天未检，超过 ${MAX_STALE_DAYS} 天上限"; return 1; }

  return 0
}

# ── 缓存命中，直接放行 ───────────────────────────────────────
print_cache_hit() {
  local current_head
  current_head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)
  local short_h="${current_head:0:8}"
  local age_h
  age_h=$(hours_since "$CACHED_LASTCHECK")
  echo "✅ 预检缓存命中（commit ${short_h}，距今 ${age_h}h），静默放行"
  echo "   → 强制重检：$0 --force"
  echo "   → 查看状态：$0 --status"
}

# ── 打勾持久化 ─────────────────────────────────────────────────
write_cache() {
  local now head
  now=$(now_iso)
  head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)

  item_json() {
    local id="$1"
    local entry
    entry=$(get_result "$id")
    local st="${entry%%|*}"
    local note="${entry#*|}"
    note=$(printf '%s' "$note" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -s ' ' ' ')
    printf '    "%s": { "status": "%s", "note": "%s" }' "$id" "$st" "$note"
  }

  # 用换行分隔，最后一行不加逗号
  local all="" sep=""
  local id
  for id in code-version workspace deps-backend deps-frontend config secrets data; do
    all="${all}${sep}$(item_json "$id")"
    sep=",
"
  done

  cat > "$CHECKED_FILE" <<EOF
{
  "_comment": "本地预检打勾状态。此文件已被 .gitignore 覆盖，不会提交到 git。由 pre-run-check.sh 自动生成。",
  "schemaVersion": "1",
  "lastCheck": "$now",
  "headAtCheck": "$head",
  "targetBranch": "$TARGET_BRANCH",
  "checks": {
$all
  }
}
EOF
}

# ── 校验项 ────────────────────────────────────────────────────

_check_code_version() {
  local name="核心代码版本对齐"
  git -C "$ROOT" fetch origin --quiet 2>/dev/null || {
    report fail code-version "$name" "无法 fetch origin - 请确认网络和远程仓库权限"
    return
  }
  local target_rev local_rev merge_base ahead
  target_rev=$(git -C "$ROOT" rev-parse "${TARGET_BRANCH}" 2>/dev/null || echo "")
  [ -n "$target_rev" ] || {
    report fail code-version "$name" "无法解析基准分支 ${TARGET_BRANCH} - 请确认已 fetch 或配置正确"
    return
  }
  local_rev=$(git -C "$ROOT" rev-parse HEAD)
  merge_base=$(git -C "$ROOT" merge-base HEAD "${TARGET_BRANCH}" 2>/dev/null || echo "")
  if [ "$local_rev" = "$target_rev" ]; then
    report ok code-version "$name" "本地与 ${TARGET_BRANCH} 一致 (${local_rev:0:8})"
  elif [ "$merge_base" = "$target_rev" ]; then
    ahead=$(git -C "$ROOT" rev-list --count "${TARGET_BRANCH}..HEAD" 2>/dev/null)
    report fail code-version "$name" "本地超前 ${TARGET_BRANCH} ${ahead} 个 commit - 请先推送/合并，或切回团队基准"
  elif [ "$merge_base" = "$local_rev" ]; then
    local behind
    behind=$(git -C "$ROOT" rev-list --count "HEAD..${TARGET_BRANCH}" 2>/dev/null)
    report fail code-version "$name" "落后 ${TARGET_BRANCH} ${behind} 个 commit - 请 git pull / rebase"
  else
    report fail code-version "$name" "本地与 ${TARGET_BRANCH} 已分叉 - 请 rebase/merge 后再运行"
  fi
}

_check_workspace() {
  local name="code/ 工作区状态"
  local dirty
  dirty=$(git -C "$ROOT" status --porcelain -- code/sewpg-bid-backend code/sewpg-bid-frontend 2>/dev/null | wc -l | tr -d ' ')
  if [ "$dirty" -eq 0 ]; then
    report ok workspace "$name" "code/ 工作区干净"
  else
    report warn workspace "$name" "code/ 有 $dirty 处未提交变更 - 请逐项确认是有意保留的本地工作"
  fi
}

_check_deps_backend() {
  local name="后端 Python 依赖"
  local backend="$ROOT/code/sewpg-bid-backend"
  if [ ! -d "$backend/.venv" ]; then
    report warn deps-backend "$name" ".venv 缺失 - 首次或依赖变更后需重新安装"
  elif [ -f "$backend/requirements.txt" ] && [ "$backend/requirements.txt" -nt "$backend/.venv" ]; then
    report warn deps-backend "$name" "requirements.txt 新于 .venv - 建议重新安装依赖"
  else
    report ok deps-backend "$name" ".venv 存在，依赖锁文件未新于安装目录"
  fi
}

_check_deps_frontend() {
  local name="前端 Node 依赖"
  local frontend="$ROOT/code/sewpg-bid-frontend"
  if [ -f "$frontend/package-lock.json" ]; then
    if [ -d "$frontend/node_modules" ] \
       && [ -z "$(find "$frontend/node_modules" -maxdepth 0 -type d -empty 2>/dev/null)" ]; then
      if [ "$frontend/package-lock.json" -nt "$frontend/node_modules" ]; then
        report warn deps-frontend "$name" "package-lock.json 新于 node_modules - 需 npm ci"
      else
        report ok deps-frontend "$name" "node_modules 就绪，锁文件未新于安装目录"
      fi
    else
      report warn deps-frontend "$name" "package-lock.json 存在但 node_modules 缺失 - 需 npm ci"
    fi
  else
    report warn deps-frontend "$name" "package-lock.json 缺失 - 需 npm install"
  fi
}

_check_config() {
  local name="本地 .env 配置完整"
  if [ ! -f "$ROOT/code/.env" ]; then
    report fail config "$name" "code/.env 缺失 - 请从 .env.example 创建"
    return
  fi
  local missing=""
  grep -qE '^DATABASE_URL='    "$ROOT/code/.env" || missing="$missing DATABASE_URL"
  grep -qE '^MINIO_ENDPOINT='   "$ROOT/code/.env" || missing="$missing MINIO_ENDPOINT"
  grep -qE '^REDIS_URL='        "$ROOT/code/.env" || missing="$missing REDIS_URL"
  grep -qE '^OPENCODE_BASE_URL=' "$ROOT/code/.env" || missing="$missing OPENCODE_BASE_URL"
  if [ -z "$missing" ]; then
    report ok config "$name" ".env 关键配置已填入"
  else
    report fail config "$name" "关键配置项缺失：$missing"
  fi
}

_check_secrets() {
  local name="LLM / OCR 密钥 / 权限"
  local f="$ROOT/start_checklist/team-bootstrap.local.yaml"
  if [ ! -f "$f" ]; then
    report warn secrets "$name" "未找到 team-bootstrap.local.yaml - 请确认运行环境已配置"
    return
  fi
  if grep -qE 'apiKey:[[:space:]]*sk-' "$f" 2>/dev/null; then
    report warn secrets "$name" "team-bootstrap.local.yaml 中含 apiKey - 请确认未过期且不会误提交"
  else
    report warn secrets "$name" "team-bootstrap.local.yaml 中未检测到 apiKey - 请确认运行环境已配置"
  fi
}

_check_data() {
  local name="素材目录就绪"
  if [ -d "$ROOT/code/.localdata" ]; then
    report ok data "$name" ".localdata 已就绪（素材默认动态加载）"
  else
    report warn data "$name" ".localdata 不存在 - 首次运行将自动生成"
  fi
}

# ── --status：只看打勾状态 ────────────────────────────────────
if $STATUS_ONLY; then
  if load_cache 2>/dev/null; then
    echo "=== 预检打勾状态（${CACHED_LASTCHECK:-未知}） ==="
    for id in code-version workspace deps-backend deps-frontend config secrets data; do
      entry=""
      entry=$(sed -n "s/.*\"$id\"[[:space:]]*:[[:space:]]*{[[:space:]]*\"status\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\"[[:space:]]*,[[:space:]]*\"note\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\1|\2/p" "$CHECKED_FILE")
      st="${entry%%|*}"
      note="${entry#*|}"
      icon=""
      case "$st" in
        ok)   icon="✅";;
        warn) icon="⚠️ ";;
        fail) icon="❌";;
        *)    icon="⬜";;
      esac
      printf "  %s  %-16s %s\n" "$icon" "$id" "$note"
    done
  else
    echo "暂无预检记录，请运行 $0 完成首次预检。"
  fi
  exit 0
fi

# ── 主流程 ────────────────────────────────────────────────────
if load_cache 2>/dev/null; then
  if cache_valid; then
    print_cache_hit
    exit 0
  fi
  echo "⚠️   ${CACHE_INVALID_REASON}，重新预检"
  echo
else
  echo "⓵   首次预检（尚无本地缓存）"
  echo
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  bid-project-mvp 本地运行预检"
echo "  基准分支: $TARGET_BRANCH | 缓存上限: ${MAX_STALE_DAYS} 天"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

echo "── [1/6] 代码版本 ────────────────────────────────────"
_check_code_version
_check_workspace

echo
echo "── [2/6] 依赖基线 ────────────────────────────────────"
_check_deps_backend
_check_deps_frontend

echo
echo "── [3/6] 配置 ────────────────────────────────────────"
_check_config

echo
echo "── [4/6] 密钥 / 权限 ─────────────────────────────────"
_check_secrets

echo
echo "── [5/6] 素材 / 数据 ──────────────────────────────────"
_check_data

echo
echo "── [6/6] 判定 ────────────────────────────────────────"
if [ "$FAIL" -gt 0 ]; then
  echo "❌  有 ${FAIL} 项必检项未通过，请解决后再运行项目"
  echo
  write_cache
  exit 1
fi
if [ "$WARN" -gt 0 ]; then
  echo "⚠️   必检项全部通过，有 ${WARN} 项推荐项未通过（不阻断，请知悉）"
else
  echo "✅  全部预检项通过"
fi
echo
write_cache
echo "   打勾状态已写入 .checked.local.json — 下次启动如代码/配置未变更将自动跳过"
echo "   强制重检：$0 --force  |  查看状态：$0 --status"
exit 0
