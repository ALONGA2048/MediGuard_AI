#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -eq 0 ]]; then
  echo '請以桌面登入使用者執行 bash scripts/install.sh，不要 sudo 整支腳本。' >&2
  exit 1
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# systemd ExecStart/EnvironmentFile and desktop Exec need escaping for special paths.
# Fail clearly rather than silently install a broken command.
if [[ "$ROOT" =~ [[:space:]\%\"\\] ]]; then
  echo '請先將此資料夾移至不含空白、%、引號或反斜線的路徑，例如 ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch' >&2
  exit 1
fi
sudo apt-get update
source /etc/os-release
if [[ "${ID:-}" == ubuntu ]]; then
  sudo apt-get install -y python3 snapd fonts-noto-cjk curl
  sudo systemctl enable --now snapd.socket
  sudo snap wait system seed.loaded
  if ! snap list chromium >/dev/null 2>&1; then
    sudo snap install chromium
  fi
else
  sudo apt-get install -y python3 chromium fonts-noto-cjk curl
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
# XDG desktop autostart runs after the GUI, so Wayland/X11 session vars are present.
cat > "$HOME/.config/autostart/mediguard-pos.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MediGuard 8-inch terminal
Exec=$ROOT/scripts/kiosk.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
echo '已安裝本機服務與桌面自動啟動。請設定 1280x800、桌面自動登入及關閉螢幕休眠，再重新登入。'
echo '現在可手動執行：bash scripts/kiosk.sh'
echo 'Ubuntu Server 請先依 README 安裝 ubuntu-desktop-minimal；本腳本不會自動安裝桌面或修改網路。'
