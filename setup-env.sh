#!/bin/bash
# setup-env.sh — copies .env from main worktree if missing
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$SCRIPT_DIR/.env"

if [ -f "$TARGET" ]; then
  echo "✅ .env already exists"
  exit 0
fi

MAIN="$HOME/code/archimedes-arcadia/.env"
if [ -f "$MAIN" ]; then
  cp "$MAIN" "$TARGET"
  echo "✅ Copied .env from main worktree"
else
  echo "❌ No .env found in main worktree ($MAIN)"
  echo "   Create one with: CIRCLE_API_KEY=... CIRCLE_ENTITY_SECRET=... WALLET_ID=... WALLET_ADDRESS=..."
  exit 1
fi
