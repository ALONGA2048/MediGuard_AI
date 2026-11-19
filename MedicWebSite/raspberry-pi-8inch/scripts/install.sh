#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -eq 0 ]]; then
  echo '請以 kiosk 登入使用者執行 bash scripts/install.sh，不要 sudo 整支腳本。' >&2
  exit 1
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# systemd ExecStart/EnvironmentFile and desktop Exec need escaping for special paths.
# Fail clearly rather than silently install a broken command.
if [[ "$ROOT" =~ [[:space:]\%\"\\] ]]; then
  echo '請先將此資料夾移至不含空白、%、引號或反斜線的路徑，例如 ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch' >&2
  exit 1
fi
source /etc/os-release
DESKTOP="${KIOSK_DESKTOP:-auto}"
if [[ "$DESKTOP" == auto ]]; then
  if [[ "${ID:-}" == raspbian || -f /etc/rpi-issue ]] || command -v openbox-session >/dev/null; then
    DESKTOP=openbox
  else
    DESKTOP=xdg
  fi
fi
case "$DESKTOP" in
  openbox|xdg) ;;
  *) echo 'KIOSK_DESKTOP 只支援 auto、openbox、xdg。' >&2; exit 1 ;;
esac
# Minimal kiosk systems can provision packages separately and install only services:
# SKIP_PACKAGE_INSTALL=1 bash scripts/install.sh
if [[ "${SKIP_PACKAGE_INSTALL:-0}" != 1 ]]; then
  sudo apt-get update
  if [[ "${ID:-}" == ubuntu ]]; then
    sudo apt-get install -y --no-install-recommends python3 snapd fonts-noto-cjk curl
    sudo systemctl enable --now snapd.socket
    sudo snap wait system seed.loaded
    if ! snap list chromium >/dev/null 2>&1; then
      sudo snap install chromium
    fi
  else
    sudo apt-get install -y --no-install-recommends python3 chromium fonts-noto-cjk curl
  fi
  if [[ "$DESKTOP" == openbox ]]; then
    sudo apt-get install -y --no-install-recommends \
      xserver-xorg xserver-xorg-input-libinput openbox lightdm lightdm-gtk-greeter \
      xterm x11-xserver-utils dbus-x11 util-linux
  fi
fi
for dependency in python3 curl flock; do
  command -v "$dependency" >/dev/null || { echo "缺少必要指令：$dependency" >&2; exit 1; }
done
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null && [[ ! -x /snap/bin/chromium ]]; then
  echo '缺少 Chromium；請先安裝瀏覽器。' >&2
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11 以上")'
if [[ "$DESKTOP" == openbox ]]; then
  for dependency in openbox-session Xorg xset; do
    command -v "$dependency" >/dev/null || { echo "Openbox 模式缺少必要指令：$dependency" >&2; exit 1; }
  done
fi
mkdir -p "$ROOT/data" "$HOME/.config/autostart"
if [[ ! -f "$ROOT/.env" ]]; then cp "$ROOT/.env.example" "$ROOT/.env"; fi
chmod 600 "$ROOT/.env"
chmod +x "$ROOT/scripts/kiosk.sh"
UNIT="$(mktemp)"
trap 'rm -f -- "$UNIT"' EXIT
cat > "$UNIT" <<EOF
[Unit]
Description=MediGuard 8-inch local terminal
After=network.target

[Service]
Type=simple
User=$(id -un)
Group=$(id -gn)
WorkingDirectory=$ROOT
ExecStart=/usr/bin/python3 $ROOT/server.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 "$UNIT" /etc/systemd/system/mediguard-pos.service
sudo systemctl daemon-reload
sudo systemctl enable --now mediguard-pos.service
if [[ "$DESKTOP" == openbox ]]; then
  mkdir -p "$HOME/.config/openbox"
  # Preserve user settings; replace only our block and known earlier launch lines.
  python3 - "$HOME/.config/openbox/autostart" "$ROOT/scripts/kiosk.sh" <<'PY'
import re
import shutil
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
launcher = sys.argv[2]
old = path.read_text() if path.exists() else ''
begin, end = '# BEGIN MEDIGUARD KIOSK', '# END MEDIGUARD KIOSK'
text = re.sub(r'(?ms)^# BEGIN MEDIGUARD KIOSK\n.*?^# END MEDIGUARD KIOSK\n?', '', old)
for command in (f'"{launcher}"', '"$HOME/MediGuard_AI/MedicWebSite/raspberry-pi-8inch/scripts/kiosk.sh"',
                'chromium "file://$HOME/browser-test.html"',
                'epiphany "file://$HOME/mediguard-browser-test.html"'):
    text = re.sub(r'(?m)^' + re.escape(command) + r'(?:[ \t]*\\\n[^\n]*|[^\n]*)\n?', '', text)
block = f'{begin}\n"{launcher}" &\n{end}\n'
new = text.rstrip() + '\n\n' + block
if new != old:
    if path.exists():
        shutil.copy2(path, str(path) + '.backup-' + str(time.time_ns()))
    path.write_text(new)
PY
  # Hidden=true also suppresses a previous XDG launcher in Openbox.
  cat > "$HOME/.config/autostart/mediguard-pos.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MediGuard 8-inch terminal
Hidden=true
EOF
else
  # XDG desktop autostart runs after the GUI session is ready.
  cat > "$HOME/.config/autostart/mediguard-pos.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MediGuard 8-inch terminal
Exec=$ROOT/scripts/kiosk.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
fi
echo "已安裝本機服務與 $DESKTOP 自動啟動；既有 .env 與 data 保留。"
echo '現在可手動執行：bash scripts/kiosk.sh'
echo '腳本不會切換 display manager、啟用自動登入、修改網路或重新啟動桌面。'
if [[ "$DESKTOP" == openbox ]]; then
  echo '請在 LightDM 選 Openbox session；測試正常後再設定自動登入。'
  echo '請移除其他自行加入的瀏覽器自啟命令，避免同時執行多個瀏覽器。'
fi
