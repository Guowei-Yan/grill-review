#!/usr/bin/env bash
# Sync grill-yagni plus its deterministic helper to local agent installs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SRC:-$SCRIPT_DIR/SKILL.md}"
HELPER_SRC="$SCRIPT_DIR/../grill-review/scripts"
HELPERS=(grill-review.py grill_review_engine.py grill_review_ingest.py grill_review_validation.py grill_review_returns.py)

[ -f "$SRC" ] || { echo "✗ source not found: $SRC" >&2; exit 1; }
for helper in "${HELPERS[@]}"; do
  [ -f "$HELPER_SRC/$helper" ] || {
    echo "✗ helper not found: $HELPER_SRC/$helper" >&2
    exit 1
  }
done

copy_helpers() {
  local destination="$1" helper
  mkdir -p "$destination"
  for helper in "${HELPERS[@]}"; do
    cp "$HELPER_SRC/$helper" "$destination/$helper"
  done
  chmod +x "$destination/grill-review.py"
}

written=""
sync_skills_dir() {
  local skills_dir="$1" canon destination
  mkdir -p "$skills_dir"
  canon="$(cd "$skills_dir" && pwd -P)"
  if printf '%s' "$written" | grep -qxF "$canon"; then
    echo "↩ skip    $skills_dir  (symlink → already-synced target)"
    return
  fi
  written="$written$canon"$'\n'
  destination="$skills_dir/grill-yagni"
  mkdir -p "$destination"
  cp "$SRC" "$destination/SKILL.md"
  copy_helpers "$destination/scripts"
  echo "✓ synced  $destination"
}

PRIMARY_ROOTS=("$HOME/.claude" "$HOME/.codex" "$HOME/.cursor")
OPTIONAL_ROOTS=(
  "$HOME/.agents"
  "$HOME/.config/opencode"
  "$HOME/.config/muse"
  "$HOME/.gemini/config"
  "$HOME/.pi/agent"
  "$HOME/.zcode"
  "$HOME/.kimicode"
)
for root in "${PRIMARY_ROOTS[@]}"; do
  sync_skills_dir "$root/skills"
done
for root in "${OPTIONAL_ROOTS[@]}"; do
  if [ -d "$root" ]; then
    sync_skills_dir "$root/skills"
  fi
done

# Include real project-scoped agent installs, pruning macOS TCC-protected folders,
# node_modules, temporary/cache directories, and this repo's own sources.
while IFS= read -r skills_dir; do
  sync_skills_dir "$skills_dir"
done < <(find "$HOME" -maxdepth 6 \
  \( -path "$HOME/Library" -o -path "$HOME/Desktop" -o -path "$HOME/Documents" \
     -o -path "$HOME/Downloads" -o -path "$HOME/.*" -o -path '*/node_modules' \
     -o -path '*/.tmp' -o -path '*/cache' -o -path "$(dirname "$SCRIPT_DIR")" \) -prune \
  -o -type d -path '*/.agents/skills' ! -path "$HOME/.agents/skills" ! -path '*backup*' -print 2>/dev/null)

CURSOR_RULES_DIR="${CURSOR_RULES_DIR:-$HOME/.cursor/rules}"
CURSOR="$CURSOR_RULES_DIR/grill-yagni.mdc"
mkdir -p "$(dirname "$CURSOR")"
{
  cat <<'CURSOR_FRONTMATTER'
---
description: Use when an exhaustive repeated over-engineering review is needed for a branch, PR, pasted diff, or explicitly listed files; when every changed hunk or whole target-file section must be checked for code or prose that can be deleted or shrunk without changing requested behaviour.
globs:
alwaysApply: false
---
CURSOR_FRONTMATTER
  awk 'f>=2{print} /^---$/{f++}' "$SRC"
} > "$CURSOR"
copy_helpers "$HOME/.local/share/grill-review"
echo "✓ synced  $CURSOR"
echo "✓ synced  $HOME/.local/share/grill-review"
echo "Done — grill-yagni and helper synced."
