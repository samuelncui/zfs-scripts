#!/usr/bin/env bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  exec sudo \
    TR_TORRENT_DIR="${TR_TORRENT_DIR:-}" \
    TR_TORRENT_NAME="${TR_TORRENT_NAME:-}" \
    "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd ${SCRIPT_DIR}

ENV_FILE="${SCRIPT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ -z "${TR_TORRENT_DIR:-}" ]; then
    echo "TR_TORRENT_DIR not set"
    exit 1
fi
if [ -z "${TR_TORRENT_NAME:-}" ]; then
    echo "TR_TORRENT_NAME not set"
    exit 1
fi
if [ -z "${TARGET_DIR:-}" ]; then
    echo "TARGET_DIR not set"
    exit 1
fi

exec python3 "${SCRIPT_DIR}/transmission_finish.py" \
  --source "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" \
  --target "${TARGET_DIR}/${TR_TORRENT_NAME}"
