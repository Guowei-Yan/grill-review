#!/usr/bin/env bash
# Sync grill-diff plus its deterministic helper to all local agent installs.
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

# Local agent hosts. Canonicalise roots so symlinked skill directories are
# installed once without duplicate registration.
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
  destination="$skills_dir/grill-diff"
  mkdir -p "$destination"
  cp "$SRC" "$destination/SKILL.md"
  copy_helpers "$destination/scripts"
  echo "✓ synced  $destination"
}

for root in "$HOME/.agents" "$HOME/.claude" "$HOME/.codex" \
  "$HOME/.config/opencode" "$HOME/.config/muse" "$HOME/.cursor" \
  "$HOME/.gemini/config" "$HOME/.pi/agent" "$HOME/.zcode" "$HOME/.kimicode"; do
  sync_skills_dir "$root/skills"
done

# Include real project-scoped agent installs, but never temporary plugin/cache roots
# or this repo's own sources.
while IFS= read -r skills_dir; do
  sync_skills_dir "$skills_dir"
done < <(find "$HOME" -mindepth 3 -maxdepth 6 -type d -path '*/.agents/skills' \
  ! -path "$HOME/.*" ! -path '*/.tmp/*' ! -path '*/cache/*' ! -path '*backup*' \
  ! -path "$(dirname "$SCRIPT_DIR")/*" \
  -print 2>/dev/null)

# Cursor consumes an .mdc rule. Its helper fallback is shared by all rules.
CURSOR_RULES_DIR="${CURSOR_RULES_DIR:-$HOME/.cursor/rules}"
CURSOR="$CURSOR_RULES_DIR/grill-diff.mdc"
mkdir -p "$(dirname "$CURSOR")"
{
  cat <<'CURSOR_FRONTMATTER'
---
description: Use when an exhaustive repeated review is needed for a branch, PR, pasted diff, or explicitly listed files; when every changed hunk or whole target-file section must be checked, supporting behaviour or planning documents may define correctness, and false positives must be filtered before reporting.
globs:
alwaysApply: false
---
CURSOR_FRONTMATTER
  awk 'f>=2{print} /^---$/{f++}' "$SRC"
} > "$CURSOR"
copy_helpers "$HOME/.local/share/grill-review"
echo "✓ synced  $CURSOR"
echo "✓ synced  $HOME/.local/share/grill-review"
echo "Done — grill-diff and helper synced."
