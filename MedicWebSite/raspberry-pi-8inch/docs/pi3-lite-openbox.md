# Raspberry Pi 3B：Pi OS Lite 32 位元＋Openbox

目標：1 GB RAM 的 Pi 3B、HDMI／USB 觸控、單一 Chromium kiosk 與本機 Python／SQLite 服務。這是減少常駐元件的配置，不保證特定 SD 卡、供電或瀏覽器版本不會故障。先在另一張 SD 卡驗證，保留原系統。

## 1. 基礎系統

用 Raspberry Pi Imager 選 Raspberry Pi 3 與目前受支援的 Raspberry Pi OS Lite（32-bit），設定使用者、密碼、SSH、2.4 GHz Wi-Fi、Asia/Taipei。Pi 3B 沒有 5 GHz Wi-Fi。以下假設帳號 master，專案在 `~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch`。Python 需 3.11 以上。

SSH 登入新系統，先更新並重開機：

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

## 2. 安裝器

複製專案後，以登入使用者執行，不要 sudo 整支腳本：

```bash
cd ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch
KIOSK_DESKTOP=openbox bash scripts/install.sh
```

Pi OS 分支只用 APT 原生 Chromium；所有套件安裝使用 `--no-install-recommends`。Openbox 模式安裝 Xorg、libinput、Openbox、LightDM／GTK greeter、xterm、xset、D-Bus 與基本執行依賴，不安裝 GNOME 桌面或 Snap。

**已按先前流程安裝完成依賴時：**

```bash
KIOSK_DESKTOP=openbox SKIP_PACKAGE_INSTALL=1 bash scripts/install.sh
```

此模式完全略過 APT／Snap，但仍檢查 Python、curl、flock、Chromium、Openbox、Xorg、xset。安裝器保留 `.env`／`data`，建立 systemd 網站服務，並在 `~/.config/openbox/autostart` 管理一個標記區塊；修改前備份原檔，重跑不重複新增。會移除本指南先前提供的已知 Chromium／Epiphany 測試頁自啟行和舊版 kiosk 啟動行，其餘自訂內容保留；其他自行設定的瀏覽器自啟仍須檢查。

XDG 的 `mediguard-pos.desktop` 會設為 `Hidden=true`，避免另一個自啟入口。安裝器不會切換顯示管理器、不寫自動登入設定、不重啟桌面或修改網路。若本機另有 GDM，先處理顯示管理器選擇；不要同時啟動 GDM 與 LightDM。

## 3. 驗證服務，再啟動桌面

```bash
systemctl is-active mediguard-pos
curl --fail --max-time 5 http://127.0.0.1:8088/api/status
```

如果改過 `POS_PORT`，curl 也改用該埠。

全新 Lite 系統可建立專用 LightDM 設定：

```bash
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/90-mediguard.conf >/dev/null <<'EOF'
[Seat:*]
greeter-session=lightdm-gtk-greeter
user-session=openbox
EOF
sudo systemctl start lightdm
```

在 HDMI 螢幕登入並選 Openbox。安裝器已建立 kiosk 自啟，不要再手動加第二行。先驗證點選、捲動、保存及 SSH 是否順暢。瀏覽器預設使用硬體加速；沒有預設 `--disable-gpu`，也不關閉沙箱。原生 Chromium 使用 `~/.config/mediguard-chromium`，不會沿用 Snap profile。

瀏覽器磁碟快取目標上限 32 MiB、媒體快取 8 MiB；這些不是瀏覽器總 RAM／profile 大小限制。停用擴充功能與帳號同步，X11 session 停用螢幕保護／DPMS。保留 Chromium 的程序隔離。

## 4. 穩定後才啟用自動登入

以下設定讓能接觸設備的人直接進入 master。若帳號不同，改為實際名稱；已有自訂 LightDM 設定請先備份合併。

```bash
sudo tee /etc/lightdm/lightdm.conf.d/90-mediguard.conf >/dev/null <<'EOF'
[Seat:*]
greeter-session=lightdm-gtk-greeter
user-session=openbox
autologin-user=master
autologin-session=openbox
autologin-user-timeout=0
EOF
sudo systemctl enable lightdm
sudo systemctl set-default graphical.target
sudo reboot
```

## 5. 日誌及診斷選項

```bash
tail -n 60 ~/.local/state/mediguard/kiosk.log
journalctl -u mediguard-pos -n 60 --no-pager
free -h
vmstat 1 5
```

啟動器在日誌列出實際瀏覽器、profile、URL 及 GPU 診斷選項。不輸出 `.env` 的同步 Token。日誌超過 1 MiB 時，下次啟動保留一份 `.previous`；單次長時間執行期間仍可能超過此值。

| 環境變數 | 用途 |
| --- | --- |
| `KIOSK_READY_TIMEOUT=60` | 等待本機 API 的上限秒數，逾時記錄原因並退出 |
| `KIOSK_DISABLE_GPU=1` | 僅供 GPU 故障交叉測試，可能增加 CPU 負擔 |
| `CHROMIUM_BIN=/usr/bin/chromium` | 明確指定瀏覽器可執行檔的完整路徑 |
| `KIOSK_PROFILE=/完整路徑` | 診斷用獨立 profile，舊瀏覽器草稿不會顯示 |
| `KIOSK_RESTART=1` | 瀏覽器退出後重啟；啟動後 10 秒內退出則停止重試 |

這些是 launcher 環境變數，不從伺服器 `.env` 讀取。要長期設定，在 Openbox 標記區塊之前加入如 `export KIOSK_DISABLE_GPU=1`；不要另外新增 kiosk 呼叫。未設定 `KIOSK_RESTART` 時，Alt+F4 退出後不會重開。

若整台變慢，透過 SSH 或本機文字終端執行：

```bash
sudo systemctl set-default multi-user.target
sudo systemctl stop lightdm
```

先讓系統恢復，再分析記憶體、SD 卡／I/O、供電與瀏覽器日誌。不要用 `--no-sandbox` 或關閉 AppArmor 當作效能調整。
