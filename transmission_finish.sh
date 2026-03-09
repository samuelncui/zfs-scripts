#!/usr/bin/env bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd ${SCRIPT_DIR}

ENV_FILE="${SCRIPT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

exec python3 "${SCRIPT_DIR}/transmission_finish.py" \
  --source "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" \
  --target "${TARGET_DIR}/${TR_TORRENT_NAME}"
