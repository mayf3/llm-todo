#!/usr/bin/env bash
# ============================================================================
# Remote Sync Script for LLM Todo
# Push web files and data to a remote server (Agent开发中心 or custom endpoint)
#
# Usage:
#   ./scripts/sync_remote.sh <remote_host> [remote_path]
#
# Examples:
#   ./scripts/sync_remote.sh user@<server-ip> /var/www/llm_todo
#   LLM_TODO_REMOTE_SYNC_URL=http://<server-ip> ./sync_remote.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REMOTE_HOST="${1:-}"
REMOTE_PATH="${2:-/opt/llm_todo/web}"

# Color helpers
red()   { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
blue()  { echo -e "\033[34m$*\033[0m"; }

echo ""
blue "=========================================="
blue "  LLM Todo Remote Sync"
blue "=========================================="
echo ""

# Option 1: rsync-based deploy (requires SSH access)
if [ -n "$REMOTE_HOST" ]; then
  echo "📦 Syncing web files to $REMOTE_HOST:$REMOTE_PATH ..."
  rsync -avz --delete \
    --exclude="node_modules" \
    --exclude=".git" \
    --exclude=".DS_Store" \
    "$PROJECT_DIR/web/" \
    "$REMOTE_HOST:$REMOTE_PATH"
  echo ""
  green "✅ Web files synced to $REMOTE_HOST"
fi

# Option 2: API-based sync (calls the local server to push data to remote)
if [ -n "${LLM_TODO_REMOTE_SYNC_URL:-}" ]; then
  echo "☁️  Pushing data snapshot to $LLM_TODO_REMOTE_SYNC_URL ..."
  # Trigger the local Python server's sync endpoint
  SYNC_RESULT=$(curl -s -X POST "http://127.0.0.1:${LLM_TODO_PORT:-8720}/api/sync" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"$LLM_TODO_REMOTE_SYNC_URL\", \"token\": \"${LLM_TODO_REMOTE_SYNC_TOKEN:-}\"}")
  echo "$SYNC_RESULT" | python3 -m json.tool 2>/dev/null || echo "$SYNC_RESULT"
  echo ""
  green "✅ Data snapshot pushed"
fi

# Option 3: Export web files as a tar archive (for manual deploy)
ARCHIVE="$PROJECT_DIR/dist/llm_todo-web-$(date +%Y%m%d-%H%M%S).tar.gz"
mkdir -p "$PROJECT_DIR/dist"
tar -czf "$ARCHIVE" -C "$PROJECT_DIR/web" .
echo "📦 Web archive created: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

echo ""
green "=========================================="
green "  Sync complete!"
green "=========================================="
echo ""
