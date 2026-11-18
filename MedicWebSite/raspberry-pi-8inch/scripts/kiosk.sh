#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo '請從 Ubuntu／Raspberry Pi OS 的本機桌面終端機執行，或使用桌面自動啟動；純 Server/SSH 無 GUI session。' >&2
  exit 1
fi
if command -v flock >/dev/null; then
  exec 9>"${XDG_RUNTIME_DIR:-/tmp}/mediguard-kiosk-$(id -u).lock"
  flock -n 9 || exit 0
fi
BROWSER="$(command -v chromium || command -v chromium-browser || true)"
PROFILE="$HOME/.config/mediguard-chromium"
# Ubuntu Snap Chromium cannot use a profile in the hidden ~/.config directory.
if [[ -x /snap/bin/chromium ]]; then
  BROWSER=/snap/bin/chromium
  PROFILE="$HOME/snap/chromium/common/mediguard-chromium"
fi
[[ -n "$BROWSER" ]] || { echo '請先安裝 chromium' >&2; exit 1; }
mkdir -p "$PROFILE"
# This launcher uses the default local port. Update this URL if POS_PORT changes.
URL='http://127.0.0.1:8088'
until curl --fail --silent --max-time 2 "$URL/api/status" >/dev/null; do sleep 2; done
while true; do
  "$BROWSER" --kiosk --noerrdialogs --no-first-run --disable-session-crashed-bubble \
    --password-store=basic --overscroll-history-navigation=0 \
    --user-data-dir="$PROFILE" "$URL" || true
  # Alt+F4 exits the kiosk for maintenance. Set KIOSK_RESTART=1 for a supervised loop.
  [[ "${KIOSK_RESTART:-0}" == 1 ]] || break
  sleep 3
done
