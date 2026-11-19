> 此文件記錄舊 Ubuntu／展示清單部署。Pi 3 HDMI 藥單核對工作站請改依 ../README.md 與 pi3-lite-openbox.md，勿再安裝 GNOME 或設定舊清單同步 API。

# Ubuntu 第 4、5 步逐項操作

對應主 README 的「1280×800、自動登入、不休眠」及「Tailscale、遠端同步」。前提是已安裝 Ubuntu GNOME 桌面，並執行過 `bash scripts/install.sh`。以下標示在哪一台裝置操作，請勿把 Windows 指令貼到 Ubuntu。

## 第 4 步：設定螢幕與自動啟動

### 4-1. 在樹莓派的本機桌面設定解析度

1. 如果現在顯示 POS 全螢幕，接上鍵盤按 **Alt+F4** 回到桌面。
2. 點右上系統選單 → **Settings／設定** → **Displays／顯示器**。
3. 選 Waveshare 的 HDMI 螢幕，設定：解析度 **1280×800**、刷新率 **60Hz**（若有）、方向 **Landscape／橫向**、縮放 **100%**。
4. 按 **Apply／套用**，畫面正常後按 **Keep Changes／保留變更**。若沒有 1280×800 選項，使用主 README 第 2 節 EDID／KMS 排錯，不要任意選相近解析度。
5. 重新開 POS 時按 **Ctrl+0**，還原瀏覽器縮放。

### 4-2. 設定自動登入同一帳號

1. Settings → **System → Users**，部分介面直接顯示 Users。
2. 按 **Unlock／解鎖**，輸入管理員密碼。
3. 選擇執行 `scripts/install.sh` 的帳號，打開 **Automatic Login／自動登入**。

自動登入會直接進入該帳號的桌面，適合專用工作站。若保留手動登入，登入後一樣會開 POS。官方：[Ubuntu 自動登入](https://help.ubuntu.com/stable/ubuntu-help/user-autologin.html.en)。

### 4-3. 關閉黑屏、鎖定與休眠

在樹莓派**本機桌面**按 Ctrl+Alt+T 開終端機，使用同一帳號執行。這四行**不要加 sudo**，也不要在純 SSH 裡設定另一個人的桌面：

```bash
gsettings set org.gnome.desktop.session idle-delay 'uint32 0'
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
```

檢查並重新開機：

```bash
systemctl is-active mediguard-pos
cat ~/.config/autostart/mediguard-pos.desktop
sudo reboot
```

預期服務回傳 `active`；自啟檔的 `Exec=` 指向實際 `scripts/kiosk.sh`。重開後應出現「桌面 → 全螢幕 POS」。若服務不存在，先回專案執行 `bash scripts/install.sh`。若只有文字登入，檢查 GNOME／GDM 是否已完成安裝。

## 第 5 步：Tailscale 連線與資料同步

手機熱點提供網際網路；Tailscale 連接樹莓派、手機及接收電腦。以下先測試遠端看畫面，再設定傳資料。兩者是分開的功能。

### 5-1. 樹莓派加入 Tailscale

確認樹莓派已透過熱點上網，在其終端機執行：

```bash
curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
sh /tmp/tailscale-install.sh
sudo tailscale up
tailscale status
```

打開 `tailscale up` 顯示的登入網址，完成登入及裝置核准；之後手機、接收電腦加入同一個 tailnet。參考：[官方 Linux 安裝](https://tailscale.com/docs/install/linux)。

### 5-2. 手機查看樹莓派畫面

在樹莓派確認服務後啟用 Serve：

```bash
curl http://127.0.0.1:8088/api/status
sudo tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

第一次若印出啟用 HTTPS 的連結，開啟並依提示完成，必要時再執行 Serve。記下它顯示的真實 `https://....ts.net` 網址。

手機安裝 Tailscale、登入同一 tailnet 並啟用連線，再用瀏覽器開這個網址，應看到 POS。不要輸入手機熱點 IP 或範例網址。若熱點手機無法同時使用 VPN，換另一台加入 tailnet 的裝置測試。

此時能遠端操作樹莓派，但**尚未將紀錄同步到另一台電腦**。介面沒有獨立帳密，存取權由 tailnet 授權控制。使用 Serve，不要使用公開網際網路的 Funnel。參考：[Serve 官方說明](https://tailscale.com/docs/features/tailscale-serve)。

### 5-3. 接收電腦建立接收程式（以 Windows 為例）

1. 接收電腦安裝 [Tailscale](https://tailscale.com/download)，登入同一 tailnet。
2. 準備 Python 3.11 以上；用 `py -3 --version` 檢查，沒有則先安裝官方 Python。
3. 把整個 `raspberry-pi-8inch` 資料夾複製過去，用 PowerShell 進入該資料夾。

```powershell
# 路徑以實際放置位置為準。
cd C:\Users\你的帳號\Desktop\MediGuard_AI\MedicWebSite\raspberry-pi-8inch
py -3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 只有還沒有 .env 時才複製，避免覆蓋既有設定。
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

把剛產生的 Token 保留好，接收電腦 `.env` 填入：

```dotenv
POS_HOST=127.0.0.1
POS_PORT=8088
POS_DEVICE_ID=mediguard-receiver
POS_SYNC_URL=
POS_SYNC_TOKEN=剛產生的Token
```

值不加引號。Token 不要提交 Git 或貼到公開對話。儲存後執行：

```powershell
py -3 server.py
```

保留這個視窗；另外開一個系統管理員 PowerShell，執行：

```powershell
tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

記下**接收電腦**這次顯示的 HTTPS 網址。接收電腦先開 `http://127.0.0.1:8088`，應可看到介面。若接收端是 Linux，改依主 README 第 6 節執行 `python3 server.py` 及 `sudo tailscale serve ...`。

### 5-4. 樹莓派指向接收電腦

回樹莓派終端機：

```bash
cd ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch
nano .env
```

設定如下，其他已有變數保留：

```dotenv
POS_HOST=127.0.0.1
POS_PORT=8088
POS_DEVICE_ID=mediguard-pi-01
POS_SYNC_URL=https://接收電腦實際網址.ts.net/api/receive
POS_SYNC_TOKEN=與接收電腦完全相同的Token
```

把網址替換成接收電腦 Serve 顯示的真實網址，再接 `/api/receive`，不是樹莓派自己的網址。nano 按 **Ctrl+O → Enter** 儲存，**Ctrl+X** 離開，然後：

```bash
chmod 600 .env
sudo systemctl restart mediguard-pos
curl http://127.0.0.1:8088/api/status
```

`configured` 應為 `true`。它只代表填了網址與 Token，還需實際送資料驗證。

### 5-5. 送一筆驗證

1. 樹莓派選一個展示品項 → 確認送出清單 → 確認保存。
2. 樹莓派「交付紀錄」按「立即同步」，等約 10 秒更新。
3. 樹莓派紀錄應顯示「已同步」。
4. 接收電腦重新整理「交付紀錄」，同一筆應顯示「遠端接收」。
5. 保持接收電腦 Python 與 Tailscale 運作；本測試的 `py -3 server.py` 視窗關閉後就停止接收。正式長期部署需把接收程式設成系統服務。

若一直待傳，先查兩端 `tailscale status`、接收端 Serve 網址與服務，再比對 Token；Tailscale 裝置授權須允許對接收端 TCP 443 的存取。斷線資料會保留，恢復後每 30 秒重試。
