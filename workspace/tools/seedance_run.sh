#!/usr/bin/env bash
set -euo pipefail

PROMPT="${1:-}"
if [[ -z "${PROMPT}" ]]; then
  echo "Usage: seedance_run.sh '<prompt>'" >&2
  exit 2
fi

VENV_PY="$HOME/.venvs/openclaw/bin/python"
SCRIPT="$HOME/.openclaw/workspace/tools/seedance_generate.py"

echo "[seedance_run] VENV_PY=$VENV_PY"
echo "[seedance_run] SCRIPT=$SCRIPT"
"$VENV_PY" -c "from byteplussdkarkruntime import Ark; print('[seedance_run] import_ok')"  # 强制验证
exec "$VENV_PY" "$SCRIPT" --prompt "$PROMPT"
