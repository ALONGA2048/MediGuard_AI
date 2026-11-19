# MediGuard 8 吋直向藥單核對工作站

目標是 **Raspberry Pi 3B／1 GB、Raspberry Pi OS Lite 32 位元、Openbox、原生 Chromium、HDMI＋USB 觸控**。1280×800 螢幕在 X11 登入後預設順時針旋轉成 800×1280。

本版本已由展示品項／交付清單改成完整藥單核對流程。無 Node、React、Docker 或本機 AI 模型；網頁與 API proxy 使用 Python 3.11+ 標準函式庫。硬體服務沿用 `../raspberry_pi/hardware.py` 的 OpenCV、Flask、requests 與 rpi_ws281x。

## 操作流程

1. **掃藥單 QR Code**：按開始，透過 Camera 1 的低解析度預覽本機解碼；另支援 QR 圖片與 USB 掃碼器／原始 JSON 輸入。
2. **對準藥品**：顯示藥單待核對項目，將一項藥品放入暗箱，按開啟鏡頭，用紅色十字定位。
3. **拍照送 server**：沿用原程式同時擷取 Camera 1／2，正面以 `front_image`、反面以 `back_image` 上傳 `POST /api/v1/verifications`。
4. **顯示核對結果**：輪詢原硬體服務保存的辨識結果，依原網站藥名比對規則逐項標記；重複藥品不增加進度，`NEEDS_REVIEW`／`MISMATCH`／unknown 不標記成功。全部核對後顯示完成。

藥單與勾選清單只留在頁面記憶體，不寫 localStorage、SQLite 或 server；關閉／重新整理會失去本次藥單。瀏覽器 sessionStorage 只保存未確認拍攝的隨機 request ID，協助查詢前次結果，不存藥名。

原硬體程式仍保存照片、metadata 與 verification.json；Python proxy 另保存拍攝請求狀態，避免相同 request ID 重複拍照。舊版 `data/pos.sqlite3` 保留但不再使用，沒有自動刪除舊資料。

## 硬體沿用範圍

`hardware_service.py` 直接載入相鄰的原 `hardware.py`，不另外複製 CameraRig 或 LED 邏輯，也不執行原程式的 `__main__`。

- Camera 1 `/dev/video0`、Camera 2 `/dev/video2`，固定對焦 340／0，可由原 MEDILENS 變數覆寫。
- 保留 MJPG、1920×1080、30 FPS 輸入、先全數 grab 再 retrieve、JPEG 品質 100。
- 保留 GPIO18、65 顆 WS2812B、原可控制索引；16–31 保留區不更改。
- 正式流程固定白光 85%，拍攝後關閉可控制燈光並釋放雙鏡頭。
- **SPI LCD 強制停用**，不執行 lcd.start，不需 spidev、gpiozero、LCD 字型或 QR 顯示套件。
- 顯示用預覽預設縮小為 640×360／3 FPS，單一 `<img>` 同時供預覽與 QR 解碼；不降低實際照片解析度。原雙 Full HD 讀取仍有 CPU／USB 負擔，Pi 3 效能須實機驗證。

## 部署目錄

```text
MedicWebSite/
├── raspberry_pi/hardware.py       原鏡頭／燈光／上傳程式
└── raspberry-pi-8inch/
    ├── server.py                  輕量網站及硬體 API proxy，127.0.0.1:8088
    ├── hardware_service.py        無 SPI LCD 的硬體啟動器，127.0.0.1:5000
    ├── .env                       真實設定，不提交 Git
    ├── static/                    直向核對 UI、本機 ZXing 與授權檔
    ├── scripts/install.sh         網站服務、Openbox 自啟
    ├── scripts/install-hardware.sh 硬體依賴及 root 硬體服務
    ├── scripts/kiosk.sh           Chromium 啟動器
    └── data/                      照片與拍攝請求狀態
```

## 1. 基礎系統與網站

先依 [Pi 3 Lite／Openbox 指南](docs/pi3-lite-openbox.md) 準備新 SD 卡與圖形環境。不要再按舊 Ubuntu／GNOME 指南安裝完整桌面。

Windows PowerShell 複製必要程式，保留樹莓派既有 `.env` 與 data：

```powershell
$p = 'C:\Users\student\Desktop\MediGuard_AI\MedicWebSite'
ssh master@mediguard-pi3.local "mkdir -p ~/MediGuard_AI/MedicWebSite/raspberry_pi ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch"
scp "$p\raspberry_pi\hardware.py" master@mediguard-pi3.local:~/MediGuard_AI/MedicWebSite/raspberry_pi/
scp "$p\raspberry-pi-8inch\server.py" "$p\raspberry-pi-8inch\hardware_service.py" "$p\raspberry-pi-8inch\.env.example" master@mediguard-pi3.local:~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch/
scp -r "$p\raspberry-pi-8inch\scripts" "$p\raspberry-pi-8inch\static" master@mediguard-pi3.local:~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch/
```

樹莓派 SSH，以 master 執行：

```bash
cd ~/MediGuard_AI/MedicWebSite/raspberry-pi-8inch
KIOSK_DESKTOP=openbox bash scripts/install.sh
# 若 Python／Chromium／Xorg／Openbox 等已安裝，用這行取代上行，不執行 apt：
# KIOSK_DESKTOP=openbox SKIP_PACKAGE_INSTALL=1 bash scripts/install.sh
```

## 2. 設定 server 與硬體

編輯既有 `.env`，參考 `.env.example` 補上設定；不要覆蓋既有相機對焦與保留區顏色等實機參數：

```dotenv
POS_HOST=127.0.0.1
POS_PORT=8088
POS_HARDWARE_URL=http://127.0.0.1:5000
MEDILENS_LISTEN_PORT=5000
MEDILENS_DEVICE_TOKEN=自行產生的共同金鑰
MEDILENS_BACKEND_UPLOAD_URL=http://實際server位址:8000/api/v1/verifications
MEDILENS_BACKEND_UPLOAD_TOKEN=
```

MEDILENS_DEVICE_TOKEN 由同一份 .env 供 proxy 與硬體使用，不傳給瀏覽器。硬體 wrapper 強制僅監聽 loopback；空 Token 也只接受 loopback，建議仍設定長隨機值。server 若有 Bearer Token 驗證則設定上傳 Token。連線可使用 Tailscale 私有位址。不要沿用未確認的歷史 IP。

如果舊的 `medilens-hardware` 正在執行，先停止以免兩個程序搶鏡頭／GPIO／5000 埠：

```bash
sudo systemctl stop medilens-hardware
# 確定改由新服務接管後，停用舊服務開機啟動：
sudo systemctl disable medilens-hardware
```

安裝硬體服務（會下載必要 OpenCV／Flask／LED 依賴，不安裝 GNOME）：

```bash
bash scripts/install-hardware.sh
```

若已有可用的原硬體 Python 環境，略過套件安裝並指定它：

```bash
HARDWARE_PYTHON=/實際原環境/bin/python SKIP_HARDWARE_PACKAGES=1 bash scripts/install-hardware.sh
```

新建環境使用 venv＋APT 的 OpenCV／Flask／requests，LED 套件固定 rpi_ws281x 5.0.0；不使用 pip 安裝大份 OpenCV，也不改系統 Python。硬體服務沿用原程式以 root 控制 LED，網站服務與 Chromium 仍由一般使用者執行。

```bash
sudo systemctl restart mediguard-hardware mediguard-pos
systemctl is-active mediguard-hardware mediguard-pos
curl --fail http://127.0.0.1:8088/api/device/status
sudo systemctl restart lightdm
```

用實際 server 的 `/api/v1/health` 測試連線。未設定上傳 URL 時，拍攝仍可能保存照片，但畫面會顯示未完成，不能當作已核對。

## API 與故障恢復

瀏覽器 → 本機 Python proxy → 原硬體服務 → MedicServer。僅 Camera 1 預覽穿過 proxy，USB 鏡頭全程由原 CameraRig 管理；不另用 getUserMedia 搶占鏡頭。

- `POST /api/device/preview/start`、`/stop`：固定白光／鏡頭開關。
- `GET /api/device/preview/stream?camera=1`：同源 MJPEG。
- `POST /api/device/capture`：帶 UUID `requestId`，非同步啟動一次原硬體 capture。
- `GET /api/device/requests/{requestId}`：等待拍攝確認。
- `GET /api/device/captures/{captureId}/verification`：等待原程式保存的 server 結果。
- `GET /api/device/captures/{captureId}/camera/1|2`：顯示原始照片。

同一 request ID 不重複送出，proxy 一次只接受一個拍攝作業。連線逾時或服務重啟造成結果不明時標記 uncertain，不自動重試；畫面可查詢前次作業，請先查看硬體／server 日誌再決定下一次操作。沒有跨 MedicServer 的全域 exactly-once 保證。

本機 UI 沒有帳號系統，保留 POS_HOST=127.0.0.1；透過 Tailscale Serve 分享時，僅限獲准裝置。藥單、圖片不會傳往外部 QR 解碼網站，ZXing 已打包在 static/vendor，授權檔一併保留。

```bash
tail -n 60 ~/.local/state/mediguard/kiosk.log
journalctl -u mediguard-pos -n 60 --no-pager
sudo journalctl -u mediguard-hardware -n 60 --no-pager
```

## 開發驗證

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_workflow.mjs
node --check static/app.js
```

自動測試使用假的硬體／server，驗證 API、正反面欄位、重複請求、結果不明、不誤判 NEEDS_REVIEW、LCD 停用及自啟。部署後仍須驗證真實雙 USB 相機、GPIO 燈光、QR 清晰度、上傳、server 結果及直向觸控。
