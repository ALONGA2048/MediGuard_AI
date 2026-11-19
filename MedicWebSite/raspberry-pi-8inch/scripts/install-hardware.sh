#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -eq 0 ]]; then echo '請以登入使用者執行，不要 sudo 整支腳本。' >&2; exit 1; fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$ROOT" =~ [[:space:]\%\"\\] ]]; then echo '專案路徑不可包含空白或特殊字元。' >&2; exit 1; fi
[[ -f "$ROOT/../raspberry_pi/hardware.py" ]] || { echo '請先部署原 raspberry_pi/hardware.py 至相鄰資料夾。' >&2; exit 1; }
[[ -f "$ROOT/.env" ]] || { echo '請先執行 scripts/install.sh 建立 .env。' >&2; exit 1; }
if systemctl is-active --quiet medilens-hardware.service; then
  echo '舊 medilens-hardware 仍在使用鏡頭。請先停止該服務，再安裝此 HDMI 專用服務。' >&2
  exit 1
fi
PYTHON="${HARDWARE_PYTHON:-$ROOT/.venv-hardware/bin/python}"
if [[ "${SKIP_HARDWARE_PACKAGES:-0}" != 1 ]]; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    python3-opencv python3-flask python3-requests python3-venv python3-dev build-essential
  if [[ -z "${HARDWARE_PYTHON:-}" ]]; then python3 -m venv --system-site-packages "$ROOT/.venv-hardware"; fi
  if ! "$PYTHON" -c 'import rpi_ws281x' >/dev/null 2>&1; then
    "$PYTHON" -m pip install 'rpi_ws281x==5.0.0'
  fi
fi
[[ -x "$PYTHON" ]] || { echo "找不到硬體用 Python：$PYTHON" >&2; exit 1; }
"$PYTHON" -c 'import cv2, flask, requests, rpi_ws281x'
UNIT="$(mktemp)"
trap 'rm -f -- "$UNIT"' EXIT
cat > "$UNIT" <<EOF
[Unit]
Description=MediGuard original camera and LED service (HDMI, no SPI LCD)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$ROOT
ExecStart=$PYTHON -u $ROOT/hardware_service.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=10
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 "$UNIT" /etc/systemd/system/mediguard-hardware.service
sudo systemctl daemon-reload
sudo systemctl enable --now mediguard-hardware.service
echo '已建立 mediguard-hardware。相機／LED 沿用原程式，SPI LCD 強制停用；僅監聽 127.0.0.1。'
echo '請確認 .env 的 MEDILENS_BACKEND_UPLOAD_URL，修改後重啟 mediguard-hardware。'
