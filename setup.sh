#!/bin/bash
# setup.sh — Generate openclaw.json from the example template
# Usage: ./setup.sh [install_path]
# Example: ./setup.sh /home/myuser/.openclaw

set -e

DEFAULT_PATH="$HOME/.openclaw"
INSTALL_PATH="${1:-}"

if [ -z "$INSTALL_PATH" ]; then
  echo "Where is your openclaw installation directory?"
  echo "Press Enter to use the default: $DEFAULT_PATH"
  read -r input
  INSTALL_PATH="${input:-$DEFAULT_PATH}"
fi

# Normalize: remove trailing slash
INSTALL_PATH="${INSTALL_PATH%/}"

TEMPLATE="$(dirname "$0")/openclaw.example.json"
OUTPUT="$(dirname "$0")/openclaw.json"

if [ ! -f "$TEMPLATE" ]; then
  echo "Error: openclaw.example.json not found."
  exit 1
fi

if [ -f "$OUTPUT" ]; then
  echo "openclaw.json already exists. Overwrite? (y/N)"
  read -r confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
  fi
fi

sed "s|/home/YOUR_USER/.openclaw|$INSTALL_PATH|g" "$TEMPLATE" > "$OUTPUT"

echo ""
echo "✓ openclaw.json generated with base path: $INSTALL_PATH"
echo ""
echo "Next: fill in the remaining placeholders in openclaw.json:"
echo "  - YOUR_TELEGRAM_BOT_TOKEN"
echo "  - YOUR_TELEGRAM_USER_ID"
echo "  - YOUR_WHATSAPP_NUMBER  (if using WhatsApp)"
echo "  - YOUR_GATEWAY_AUTH_TOKEN"
echo "  - YOUR_VIDEO_SERVICE_HOST"
