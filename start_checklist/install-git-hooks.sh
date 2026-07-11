#!/usr/bin/env bash
# Install local git hooks that re-run the pre-run check after branch or code changes.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$ROOT/.git/hooks"
PRE_RUN="$ROOT/start_checklist/pre-run-check.sh"
MARKER="bid-project-mvp-pre-run-check"

install_hook() { # install_hook <hook-name>
  local hook="$HOOK_DIR/$1"
  local backup="$hook.before-pre-run-check"
  if [ -f "$hook" ] && ! grep -q "$MARKER" "$hook" 2>/dev/null; then
    if [ ! -f "$backup" ]; then
      mv "$hook" "$backup"
      chmod +x "$backup" 2>/dev/null || true
      printf 'backed up existing %s to %s\n' "$hook" "$backup"
    else
      echo "Existing hook backup already exists: $backup"
      echo "Please merge $hook manually before reinstalling."
      return 1
    fi
  fi
  cat > "$hook" <<EOF
#!/usr/bin/env bash
# $MARKER
ROOT="\$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
CHECK="\$ROOT/start_checklist/pre-run-check.sh"
BACKUP="\$ROOT/.git/hooks/$1.before-pre-run-check"
[ -x "\$BACKUP" ] && "\$BACKUP" "\$@"
[ -x "\$CHECK" ] || exit 0
"\$CHECK" --force || true
EOF
  chmod +x "$hook"
  printf 'installed %s\n' "$hook"
}

[ -d "$HOOK_DIR" ] || {
  echo "Git hooks directory not found: $HOOK_DIR"
  exit 1
}

[ -x "$PRE_RUN" ] || chmod +x "$PRE_RUN" 2>/dev/null || true

install_hook post-merge
install_hook post-checkout

echo "Git hooks installed. They are local-only and will warn after pull/checkout."
