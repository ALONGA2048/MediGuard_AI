#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$EUID" -eq 0 ]]; then
  echo '請以圖形登入使用者啟動 kiosk，不要 sudo。' >&2
  exit 1
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo '請從 Openbox／桌面 session 啟動；SSH 終端機本身沒有圖形顯示環境。' >&2
  exit 1
fi
for dependency in python3 curl flock; do
  command -v "$dependency" >/dev/null || { echo "缺少必要指令：$dependency" >&2; exit 1; }
done
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/mediguard-kiosk-$(id -u).lock"
flock -n 9 || exit 0
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mediguard"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/kiosk.log"
# Rotate at launch; retain one previous log rather than accumulating sessions.
if [[ -f "$LOG" ]] && [[ "$(wc -c < "$LOG")" -ge 1048576 ]]; then
  mv -f -- "$LOG" "$LOG.previous"
fi
exec >>"$LOG" 2>&1
printf '\n[%s] Starting kiosk\n' "$(date -Is)"
# Prefer native Chromium on Raspberry Pi OS, even if Snap is also installed.
BROWSER="${CHROMIUM_BIN:-$(command -v chromium || command -v chromium-browser || true)}"
if [[ -z "$BROWSER" && -x /snap/bin/chromium ]]; then BROWSER=/snap/bin/chromium; fi
[[ -n "$BROWSER" && -x "$BROWSER" ]] || { echo '找不到 Chromium。'; exit 1; }
PROFILE="${KIOSK_PROFILE:-$HOME/.config/mediguard-chromium}"
if [[ "$BROWSER" == /snap/* || "$(readlink -f -- "$BROWSER")" == /usr/bin/snap ]]; then
  PROFILE="${KIOSK_PROFILE:-$HOME/snap/chromium/common/mediguard-chromium}"
fi
mkdir -p "$PROFILE"
# Match server.py's literal POS_PORT parsing without sourcing secrets as shell code.
PORT="$(python3 - "$ROOT/.env" <<'PY'
import os
import sys
from pathlib import Path

port = '8088'
path = Path(sys.argv[1])
if path.exists():
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep and key.strip() == 'POS_PORT':
            port = value.strip()
            break
port = os.environ.get('POS_PORT', port)
try:
    number = int(port)
    if not 1 <= number <= 65535:
        raise ValueError
except ValueError:
    sys.exit('POS_PORT 必須為 1–65535 的整數。')
print(number)
PY
)"
URL="http://127.0.0.1:$PORT"
READY_TIMEOUT="${KIOSK_READY_TIMEOUT:-60}"
[[ "$READY_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || { echo 'KIOSK_READY_TIMEOUT 必須為正整數秒數。'; exit 1; }
deadline=$((SECONDS + READY_TIMEOUT))
until curl --noproxy '*' --fail --silent --max-time 2 "$URL/api/status" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "本機 API 在 ${READY_TIMEOUT} 秒內未就緒：$URL；請檢查 mediguard-pos.service。"
    exit 1
  fi
  sleep 2
done
FLAGS=(--kiosk --noerrdialogs --no-first-run --no-default-browser-check
  --disable-session-crashed-bubble --password-store=basic
  --overscroll-history-navigation=0 --disable-extensions --disable-sync
  --disk-cache-size=33554432 --media-cache-size=8388608
  "--user-data-dir=$PROFILE")
if [[ -n "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  FLAGS+=(--ozone-platform=x11)
  if command -v xset >/dev/null; then
    xset s off || true
    xset -dpms || true
    xset s noblank || true
  fi
fi
# Software rendering is diagnostic; it is not a default Pi 3 performance fix.
if [[ "${KIOSK_DISABLE_GPU:-0}" == 1 ]]; then FLAGS+=(--disable-gpu); fi
printf 'Browser: %s\nProfile: %s\nURL: %s\nDisable GPU: %s\n' "$BROWSER" "$PROFILE" "$URL" "${KIOSK_DISABLE_GPU:-0}"
while true; do
  started=$SECONDS
  result=0
  "$BROWSER" "${FLAGS[@]}" "$URL" || result=$?
  echo "Chromium exited: $result"
  # Alt+F4 exits by default. Supervised mode stops on rapid repeated failures.
  [[ "${KIOSK_RESTART:-0}" == 1 ]] || break
  if (( SECONDS - started < 10 )); then
    echo 'Chromium 在 10 秒內退出，停止重試；請檢查日誌。'
    exit 1
  fi
  sleep 5
done
