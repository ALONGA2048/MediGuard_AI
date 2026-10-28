# MediGuard AI

**繁體中文** | [English](README.md)

## 運行中的測試網站

目前有一個測試版網站正在運行：[開啟 MediGuard 測試網站](http://210.240.160.152:3000)。可使用網頁右上角的 **English / 繁體中文** 按鈕切換語言；是否能連線取決於您與部署網路的連通狀態。

MediGuard AI 是智慧藥物辨識原型，整合網頁介面、樹莓派雙鏡頭與燈光控制，以及 OCR／YOLO 藥物辨識後端。

> 本專案目前為開發原型。硬體拍攝與辨識流程可串接運行，但網站登入、藥單、藥品資料及部分管理畫面仍使用展示資料，請勿視為正式醫療系統。

## 專案結構

| 資料夾 | 用途 | 主要技術 | 文件 |
| --- | --- | --- | --- |
| `MedicServer/` | 接收藥品正反面照片，整合 PaddleOCR、條碼、雙角度 YOLO，並保存結果 | FastAPI、PostgreSQL、Docker Compose | [後端說明](MedicServer/README.zh-TW.md) |
| `MedicWebSite/` | 使用者介面，代理樹莓派控制、照片與辨識狀態 | React 19、Next.js 16 API、Vinext、Vite、Cloudflare Workers | [網站說明](MedicWebSite/README.zh-TW.md) |

辨識資料流程：

```text
瀏覽器
  └─> MedicWebSite（同源 API；裝置 Token 保留在伺服器）
        └─> 樹莓派（燈光、Cam1 預覽、Cam1／Cam2 拍攝）
              └─> MedicServer（front_image + back_image）
                    ├─> PaddleOCR 與條碼辨識
                    ├─> 雙角度 YOLO 分類
                    └─> PostgreSQL、JSON 結果與原始照片
```

Cam1 對應 `front_image`，Cam2 對應 `back_image`。樹莓派在背景上傳照片，網站透過樹莓派代理輪詢整合後的辨識結果。

## 主要功能

- OCR、條碼與 119 類雙角度 YOLO 藥物辨識。
- 提供預期藥品時，回傳 `MATCH`、`MISMATCH` 或 `NEEDS_REVIEW`；未提供時回傳 `IDENTIFIED` 或 `NEEDS_REVIEW`。
- 保存原始照片、完整 JSON 結果與 PostgreSQL 核對紀錄。
- 網站提供藥單、藥品查詢、辨識紀錄、裝置狀態及系統設定畫面。
- 伺服器代理樹莓派燈光、預覽、雙鏡頭拍攝、照片及辨識狀態 API。
- 手機 QR code／條碼掃描及桌面 JSON 藥單匯入。
- 網站右上角可切換繁體中文與英文，並記住瀏覽器語言偏好。

## 環境需求

- Docker Desktop 或 Docker Engine，搭配 Docker Compose v2。
- Node.js `22.13.0` 以上與 npm。
- 完整硬體流程另需樹莓派、兩個鏡頭及 WS2812B LED 燈條；觀看展示網站不需要硬體。
- PaddleOCR GPU 模式另需 NVIDIA GPU、可用的 WSL2／Docker GPU 執行環境與相容驅動。

## 快速啟動

以下從本文件所在的專案根目錄執行。

### 1. 啟動辨識後端

```powershell
Set-Location .\MedicServer
Copy-Item .env.example .env
# 編輯 .env，將 POSTGRES_PASSWORD 改為長隨機密碼
docker compose up -d --build
curl.exe http://localhost:8000/api/v1/health
```

預設地址：

- OCR／核對 API：`http://localhost:8000`
- Swagger UI：`http://localhost:8000/docs`
- PostgreSQL：`localhost:55432`
- YOLO worker：僅 Docker 內部網路可使用 `8001` 埠。

首次啟動會將 PaddleOCR 模型下載至 `MedicServer/data/paddle/`，初始化時間較長。

### 2. 啟動網站

另開 PowerShell：

```powershell
Set-Location .\MedicWebSite
Copy-Item .env.example .env.local
# 使用硬體功能前，設定樹莓派位址與共用 Token
npm install
npm run dev
```

- `http://127.0.0.1:3000/`：完整網站，登入目前是前端展示。
- `http://127.0.0.1:3001/`：辨識及本機硬體拍攝測試介面，不包含登入、藥單或藥品目錄畫面。

如需網站單容器部署，請參閱 [Docker 部署說明](MedicWebSite/docker-ver/README.md)。

### 3. 連接樹莓派（選用）

樹莓派執行 `MedicWebSite/raspberry_pi/hardware.py`，並完成以下設定：

1. `MEDILENS_DEVICE_TOKEN` 與網站的 `RASPBERRY_PI_DEVICE_TOKEN` 完全相同。
2. `MEDILENS_BACKEND_UPLOAD_URL` 指向 `http://<後端主機>:8000/api/v1/verifications`。
3. MedicServer 設定 `OCR_BIND_HOST=0.0.0.0`，主機防火牆允許樹莓派連入 TCP 8000。

安裝、鏡頭、燈條與 systemd 設定請參閱 [樹莓派部署指南](MedicWebSite/raspberry_pi/DEPLOY.md)。文件中的 `210.240.160.x` 為目前區網範例，部署至其他網路時請替換。

## 建置與驗證

網站 Worker 建置與本機啟動：

```powershell
Set-Location .\MedicWebSite
npm run lint
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
npm start
```

`vite build` 產生既有 Wrangler 啟動所需的 Worker 設定；目前 `npm run build` 使用 Vinext Node 目標。`npm start` 啟動兩個入口，詳細資訊見網站與 Docker 說明。

後端映像與單元測試：

```powershell
Set-Location .\MedicServer
docker compose build
python -m unittest discover -s tests -v
```

融合判斷單元測試不載入大型模型。完整驗證仍需啟動 Compose、檢查健康端點並提交一組正反面照片。

## GPU 模式

確認容器可使用 NVIDIA GPU 後，啟動 GPU 覆寫：

```powershell
Set-Location .\MedicServer
docker run --rm --gpus all nvidia/cuda:11.2.2-base-ubuntu20.04 nvidia-smi
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
curl.exe http://localhost:8000/api/v1/health
```

健康回應應包含 `ocr_device: "cuda:0"`、`paddle_cuda: true` 及至少一筆 `cuda_devices`。目前 GPU 覆寫同時適用 OCR 與 Pair-YOLO／OOD；選擇裝置及 CPU 切換方式請參閱後端說明。

## 關閉與資料保存

```powershell
Set-Location .\MedicServer
docker compose down
```

除非確定要刪除資料，請勿加上 `-v` 或刪除 `MedicServer/data/`；其中保存 PostgreSQL、原始照片、模型快取及辨識結果。網站開發伺服器可在終端按 `Ctrl+C` 停止。

## 其他文件

- [MedicServer API 合約](MedicServer/docs/API_CONTRACT.md)
- [網站與硬體 API 合約](MedicWebSite/docs/API_CONTRACT.md)
- [樹莓派部署指南](MedicWebSite/raspberry_pi/DEPLOY.md)
- [藥單 JSON 範例](MedicWebSite/examples/sample-prescription.json)
