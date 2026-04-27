#!/usr/bin/env sh
set -eu

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
progress_file="$repo_root/code/progress.md"

if [ ! -f "$progress_file" ]; then
  exit 0
fi

commit_hash="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
commit_subject="$(git log -1 --pretty=%s 2>/dev/null || echo 'no commit subject')"
changed_files="$(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null | sed 's/^/- `/' | sed 's/$/`/' || true)"
timestamp="$(date '+%Y-%m-%d %H:%M:%S')"

{
  printf '\n### %s post-commit %s\n\n' "$timestamp" "$commit_hash"
  printf '提交摘要：%s\n\n' "$commit_subject"
  printf '变更文件：\n\n'
  if [ -n "$changed_files" ]; then
    printf '%s\n' "$changed_files"
  else
    printf -- '- 无文件列表\n'
  fi
  printf '\n验证结果：提交后自动记录，需结合提交前测试记录确认。\n'
} >> "$progress_file"
