# 樹莓派部署

## 1. 放置檔案

將 `hardware.py` 複製到樹莓派：

```bash
scp raspberry_pi/hardware.py admin@210.240.160.159:/home/admin/yolo_env/hardware.py
```

此版本不載入 YOLO／NCNN。Python 環境只需保留 Flask、OpenCV、rpi_ws281x，以及日後啟用後端上傳時使用的 `requests`。

## 2. 設定共同金鑰

在樹莓派 `/home/admin/yolo_env/.env` 設定：

```bash
MEDILENS_DEVICE_TOKEN=請換成至少32字元的隨機內容
MEDILENS_LISTEN_HOST=0.0.0.0
MEDILENS_LISTEN_PORT=5000
MEDILENS_WEBSITE_ORIGINS=http://210.240.160.148:3000,http://210.240.160.148:3001
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
MEDILENS_BACKEND_UPLOAD_URL=http://210.240.160.148:8000/api/v1/verifications
MEDILENS_BACKEND_UPLOAD_TOKEN=
MEDILENS_RESERVED_LED_RGB=0,0,0
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

在 `210.240.160.148` 的網站專案 `.env.local` 設定相同金鑰：

```text
RASPBERRY_PI_BASE_URL=http://210.240.160.159:5000
RASPBERRY_PI_DEVICE_TOKEN=與樹莓派完全相同的金鑰
```

修改環境變數後重新啟動 `npm run dev`，區域網路使用者可經由 `http://210.240.160.148:3000` 開啟正式網站，或經由 `http://210.240.160.148:3001` 開啟測試介面。主機防火牆需允許 TCP 3000 與 3001。

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
curl http://210.240.160.148:8000/api/v1/health
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
