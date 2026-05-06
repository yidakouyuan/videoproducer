#!/usr/bin/env bash
# Cron wrapper for Douyin auto pipeline.
# Supports environment overrides:
#   HOME_ROUNDS, HOME_VIDEOS_PER_ROUND, ENRICH_LIMIT
#   HOME_INCLUDE_RELATED=1, ENRICH_FORCE=1, REQUIRE_PLAY=1, HEADFUL=1

set -uo pipefail

ROOT_DIR="/home/xinyue/workspace/video-agent-system"
PYTHON_BIN="/disk2/xinyue/envs/video/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "[fatal] python not found"
  exit 127
fi

cd "${ROOT_DIR}" || exit 1

mkdir -p data/logs/auto_pipeline_runner
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="data/logs/auto_pipeline_runner/${STAMP}.log"
exec >>"${RUN_LOG}" 2>&1

echo "[start] ts_utc=${STAMP}"
echo "[start] python=${PYTHON_BIN}"

HOME_ROUNDS="${HOME_ROUNDS:-5}"
HOME_VIDEOS_PER_ROUND="${HOME_VIDEOS_PER_ROUND:-20}"
ENRICH_LIMIT="${ENRICH_LIMIT:-100}"

CMD=(
  "${PYTHON_BIN}" "src/douyin_hot_db/run_auto_pipeline.py"
  "--db" "data/douyin_hot.db"
  "--home-rounds" "${HOME_ROUNDS}"
  "--home-videos-per-round" "${HOME_VIDEOS_PER_ROUND}"
  "--enrich-limit" "${ENRICH_LIMIT}"
)

if [[ "${HOME_INCLUDE_RELATED:-0}" == "1" ]]; then
  CMD+=("--home-include-related")
fi
if [[ "${ENRICH_FORCE:-0}" == "1" ]]; then
  CMD+=("--enrich-force")
fi
if [[ "${REQUIRE_PLAY:-0}" == "1" ]]; then
  CMD+=("--require-play")
fi
if [[ "${HEADFUL:-0}" == "1" ]]; then
  CMD+=("--headful")
fi

echo "[cmd] ${CMD[*]}"

RC=0
"${CMD[@]}" || RC=$?

echo "[end] rc=${RC}"
exit "${RC}"
