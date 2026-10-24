# 樹莓派部署

## 1. 放置檔案

將 `hardware.py` 複製到樹莓派：

```bash
scp raspberry_pi/hardware.py admin@210.240.160.159:/home/admin/yolo_env/hardware.py
```

此版本不載入 YOLO／NCNN。Python 環境使用 Flask、OpenCV、rpi_ws281x、requests，以及 SPI LCD 使用的 spidev、gpiozero、Pillow、NumPy 和 qrcode。

## 2. 設定共同金鑰

在樹莓派 `/home/admin/yolo_env/.env` 設定：

```bash
MEDILENS_DEVICE_TOKEN=請換成至少32字元的隨機內容
MEDILENS_LISTEN_HOST=0.0.0.0
MEDILENS_LISTEN_PORT=5000
MEDILENS_WEBSITE_ORIGINS=http://210.240.160.159:3000,http://210.240.160.159:3001
MEDILENS_CAMERA_1=0
MEDILENS_CAMERA_2=2
MEDILENS_CAMERA_1_FOCUS=340
MEDILENS_CAMERA_2_FOCUS=0
MEDILENS_PREVIEW_WIDTH=960
MEDILENS_PREVIEW_HEIGHT=540
MEDILENS_PREVIEW_FPS=5
MEDILENS_PREVIEW_JPEG_QUALITY=75
MEDILENS_CAPTURE_WIDTH=1920
MEDILENS_CAPTURE_HEIGHT=1080
MEDILENS_CAPTURE_FPS=30
MEDILENS_CAPTURE_DIR=/home/admin/yolo_env/captures
MEDILENS_BACKEND_UPLOAD_URL=http://210.240.160.159:8000/api/v1/verifications
MEDILENS_BACKEND_UPLOAD_TOKEN=
MEDILENS_RESERVED_LED_RGB=0,0,0
MEDILENS_LCD_ENABLED=true
MEDILENS_LCD_URL=http://210.240.160.152:3001
MEDILENS_LCD_SPI_BUS=0
MEDILENS_LCD_SPI_DEVICE=0
MEDILENS_LCD_SPI_HZ=8000000
MEDILENS_LCD_DC=25
MEDILENS_LCD_RESET=24
```

啟動前載入環境：

```bash
cd /home/admin/yolo_env
set -a
source .env
set +a
sudo -E ./bin/python hardware.py
```

## 3. 網站主機

辨識上傳目的地由樹莓派 `/home/admin/yolo_env/.env` 的 `MEDILENS_BACKEND_UPLOAD_URL` 決定，網站的 `RASPBERRY_PI_BASE_URL` 只控制網站連往硬體服務的位址。現行辨識 Server 為 `210.240.160.159:8000`。修改既有設定時保留共同金鑰，並執行 `sudo systemctl restart medilens-hardware`；若是手動啟動，必須重新載入 `.env` 後重啟 Python。只修改此儲存庫的範例不會更新運行中的裝置。

在 `210.240.160.159` 的網站專案 `.env.local` 設定相同金鑰：

```text
RASPBERRY_PI_BASE_URL=http://210.240.160.159:5000
RASPBERRY_PI_DEVICE_TOKEN=與樹莓派完全相同的金鑰
```

修改環境變數後重新啟動 `npm run dev`，區域網路使用者可經由 `http://210.240.160.159:3000` 開啟正式網站，或經由 `http://210.240.160.159:3001` 開啟測試介面。主機防火牆需允許 TCP 3000 與 3001。

## 4. 測試

```bash
curl http://210.240.160.159:5000/api/v1/health
curl -H "Authorization: Bearer $MEDILENS_DEVICE_TOKEN" http://210.240.160.159:5000/api/v1/status
curl -X POST -H "Authorization: Bearer $MEDILENS_DEVICE_TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"capture","payload":{}}' \
  http://210.240.160.159:5000/api/v1/commands
curl -X POST -H "Authorization: Bearer $MEDILENS_DEVICE_TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"shutdown_lights","payload":{}}' \
  http://210.240.160.159:5000/api/v1/commands
```

拍照行為已對齊 `yolo_classification/ocrTest.py`：兩台相機都以 MJPG、Full HD、30 FPS 保持開啟，使用固定對焦值，拍照時先對兩台相機執行 `grab()`，再分別 `retrieve()`，最後以 JPEG 品質 100 儲存。網站預覽會從 Camera 1 的 Full HD 來源縮小為低頻寬串流，不影響實際保存照片。

正式辨識拍照完成後，樹莓派會立即讓網站讀取兩張原始照片，並在背景將 Camera 1 以 `front_image`、Camera 2 以 `back_image` 上傳至 MedicServer。辨識狀態與結果會保存在該次拍攝資料夾的 `verification.json`，網站每 2 秒讀取一次，最長等待 5 分鐘。3001 測試介面的「拍照測試」會傳送 `sendToServer: false`，因此只保存及回傳照片，不會呼叫 MedicServer。

先確認樹莓派可連到辨識伺服器：

```bash
curl http://210.240.160.159:8000/api/v1/health
```

若 Python 環境尚未安裝上傳套件：

```bash
/home/admin/yolo_env/bin/pip install requests
```

## 5. systemd（選用）

複製 `medilens-hardware.service` 至 `/etc/systemd/system/`，確認 Python 路徑後：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now medilens-hardware
sudo systemctl status medilens-hardware
```

## 燈帶索引

- 會控制：`0–15`、`32–48`、`49–64`
- 固定保留：`16–31`。WS2812B 無法讀回目前顏色，所以請用 `MEDILENS_RESERVED_LED_RGB` 指定它們要保持的 RGB；預設為關閉 `0,0,0`。
- 因最高索引是 64，程式設定 `LED_COUNT = 65`。若實際燈帶只有 64 顆，請先確認你提供的索引是否應改為 `0–15`、`32–47`、`48–63`，不要直接接電測試。

## SPI LCD（依裝置實測成功程式）

目前採用使用者在實體裝置確認成功的 **ST7789 指令流程**：320×240、SPI0 CE0、8 MHz、MADCTL `0x60`、RGB565、反相關閉 `0x20`。這是依實測程式選擇的初始化流程，不是讀取晶片 ID 的判定。`MEDILENS_LCD_DRIVER` 不再參與選擇；既有 `.env` 的該項可刪除。

服務啟動時先同步初始化 LCD，建立黑底、24px 中文標題「掃描以下qrcode」及 130×130 QR Code，保存 `qrcode_preview.png`。整張畫面轉成 153600 bytes 的高位元組在前 RGB565，僅設定一次 `(0,0)-(319,239)` 視窗，再分成 4096-byte 區塊送出。完成後才啟動 Flask，不等待健康檢查、不逐行重設視窗、不清屏或重複刷新。SPI、DC 與 RESET 物件保留至服務結束。

此功能顯示標題與網站 QR Code，未實作觸控。目的地由 `MEDILENS_LCD_URL` 設定，預設為測試入口 `http://210.240.160.152:3001`。請確認手機可連到該網址；硬體 API 就緒不代表網站服務已經就緒。

中文標題使用 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`，可透過 `MEDILENS_LCD_FONT` 改路徑。與實測程式相同，需有該字型；缺少時可安裝 `fonts-noto-cjk`。

| LCD 訊號 | BCM GPIO | 實體 Pin |
| --- | --- | --- |
| SCLK | GPIO11 | 23 |
| MOSI / SDA | GPIO10 | 19 |
| CS | GPIO8（CE0） | 24 |
| DC | GPIO25 | 22 |
| RESET | GPIO24 | 18 |

MSP2807 的 VCC 支援 3.3V～5V，SPI 邏輯電位為 3.3V，GND 必須共地。依官方說明，模組第 8 腳 `LED` 是背光，高電位點亮；不使用 GPIO 控制時接樹莓派 3.3V（實體 Pin 1 或 17），不可浮接。程式不額外驅動背光 GPIO。WS2812B 保持 GPIO18（實體 Pin 12）。上表中的實體 Pin 18 是 GPIO24，請勿與 BCM GPIO18 混淆。

在樹莓派啟用 SPI 並安裝 LCD 套件：

```bash
sudo raspi-config nonint do_spi 0
/home/admin/yolo_env/bin/python -m pip install spidev gpiozero lgpio 'qrcode[pil]' pillow numpy
ls -l /dev/spidev0.0
```

若啟用 SPI 後尚無裝置節點，重新開機後再檢查。更新 `/home/admin/yolo_env/hardware.py` 與該目錄的 `.env`，保留既有 token，然後重啟服務：

```bash
sudo systemctl restart medilens-hardware
journalctl -u medilens-hardware -n 50 --no-pager
curl http://127.0.0.1:5000/api/v1/health
```

日誌應依序顯示 `[LCD] 初始化 ST7789...`、`Framebuffer bytes: 153600`、`LCD 顯示完成`，然後 Flask 才開始監聽。健康檢查的 `lcd.status` 為 `ready` 表示資料已送出；驅動流程名稱為 `st7789`。LCD 若初始化失敗，會留下錯誤並繼續啟動相機 API。無 LCD 時設 `MEDILENS_LCD_ENABLED=false`。服務結束才釋放 SPI 與 LCD 控制 GPIO；測試期間請勿同時執行獨立 LCD 測試程式。

更新 systemd 檔後，執行 `sudo systemctl daemon-reload` 再重啟。單元使用 Python `-u`，可即時在 journal 看到 LCD 啟動日誌。
