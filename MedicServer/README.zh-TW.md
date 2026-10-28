# MedicServer

**繁體中文** | [English](README.md)

MedicServer 是 MediGuard AI 的藥物辨識後端。接收正反面照片後，先執行一次 Pair-YOLO 前向推論與校準後的 cosine kNN1 OOD 閘門，再進行 PaddleOCR／條碼／資料庫辨識及具有保護條件的共識判斷，保存完整證據與最終結果。實作同步自 `drug-project` commit `9987e9347360a326cbde4c905ba918001eb28f5c`。

詳見 [流程比較與遷移說明](docs/OOD_MIGRATION.md) 及 [完整來源清單](docs/drug-project-file-inventory.csv)。

## 功能與服務架構

Docker Compose 建立三個服務：

| 服務 | 對外地址 | 用途 |
| --- | --- | --- |
| `ocr` | `http://localhost:8000` | 公開 FastAPI，負責檔案驗證、OCR／條碼、YOLO 請求、結果融合及保存 |
| `yolo` | 僅 Docker 網路 `:8001` | 載入 119 類 Pair-YOLO 與 1046 × 256 OOD bank；一次推論回傳分類與 OOD，`front -> cam0`、`back -> cam1` |
| `database` | `localhost:55432` | PostgreSQL 18；空資料庫首次初始化時匯入藥品目錄與核對資料結構 |

主要功能：

- 接收 JPEG、PNG、WEBP、TIFF、BMP 正反面照片，預設每檔上限 20 MB。
- 整合 OCR 候選、條碼結果與 YOLO 信心分數。
- 提供預期藥品時回傳 `MATCH`、`MISMATCH` 或 `NEEDS_REVIEW`。
- 未提供預期藥品時回傳 `IDENTIFIED` 或 `NEEDS_REVIEW`。
- 提供歷史紀錄、單筆結果與原始照片端點。
- 將資料保存至 PostgreSQL、本機 JSON 結果與照片資料夾。

## 資料夾配置

```text
database/init/       PostgreSQL 初始藥品資料與核對 schema
models/              Pair-YOLO、基礎 YOLO 權重與 SHA-256 檢查碼
ocr_service/         公開 API、OCR、融合與保存邏輯
yolo_service/        內部 Pair-YOLO 推論服務
                     legacy/ood_filter/ 內含校準設定與 bank
tests/               不載入模型的融合判斷測試
data/postgres/       PostgreSQL 資料
data/uploads/        每筆核對的正反面原始照片
data/results/        完整 JSON 辨識結果
data/paddle/         首次啟動建立的 PaddleOCR 模型快取
```

## 環境需求

- Docker Desktop 或 Docker Engine。
- Docker Compose v2，使用 `docker compose` 指令。
- 首次建置映像及下載 PaddleOCR 模型時需網路。
- GPU 模式需 NVIDIA GPU、相容驅動與可用的 Docker GPU 執行環境。

## CPU 快速啟動

在 `MedicServer` 執行：

```powershell
Copy-Item .env.example .env
# 編輯 .env，使用前替換 POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps
curl.exe http://localhost:8000/api/v1/health
```

Swagger UI：`http://localhost:8000/docs`。追蹤服務日誌：

```powershell
docker compose logs -f ocr yolo database
```

首次啟動會下載 PaddleOCR 模型至 `data/paddle/`，健康檢查可能較慢才就緒。CPU 映像對 PaddleOCR 2.7.3 套用經版本與內容檢查的相容性修補，並停用 MKL-DNN，避免部分 Docker 或虛擬化 CPU 發生 `SIGILL / exit 132`。

## 環境設定

使用 `.env.example` 作為範本：

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `POSTGRES_DB` | `medicine_ocr` | 資料庫名稱 |
| `POSTGRES_USER` | `medic` | 資料庫帳號 |
| `POSTGRES_PASSWORD` | 範例值 | 使用前改為長隨機密碼 |
| `POSTGRES_PORT` | `55432` | 主機對外 PostgreSQL 埠 |
| `OCR_BIND_HOST` | `0.0.0.0` | OCR 監聽介面；僅本機使用可設 `127.0.0.1` |
| `OCR_PORT` | `8000` | 主機 OCR API 埠 |
| `OCR_DEVICE` | `cpu` | 標準 Compose 的 OCR 裝置 |
| `YOLO_DEVICE` | `cpu` | YOLO 推論裝置 |
| `MAX_UPLOAD_MB` | `20` | 每張照片大小上限 |
| `FINAL_THRESHOLD` | `0.95` | 融合決策門檻 |
| `OCR_BASIC_SCORE` | `50.0` | OCR 基礎分數門檻 |
| `OCR_TIE_GAP` | `8.0` | OCR 候選分數差距門檻 |
| `OCR_SUPPORTED_YOLO_THRESHOLD` | `0.60` | 傳給上游混合判斷函式的門檻 |
| `YOLO_GPU_DEVICE` | `cuda:0` | GPU Compose 的 Pair-YOLO／OOD 裝置 |
| `OCR_GPU_DEVICE` | `0` | GPU Compose 的 PaddleOCR 裝置 |

調整後執行 `docker compose up -d --build` 重新建置與啟動。

## 核對 API

提交正反面照片：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/verifications `
  -F "front_image=@C:\path\front.jpg" `
  -F "back_image=@C:\path\back.jpg" `
  -F "expected_name=Concor 5mg"
```

`expected_name` 與 `expected_drug_id` 都是選填；同時提供時以 `expected_drug_id` 優先。

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | OCR、YOLO、資料庫與運算裝置狀態 |
| `POST` | `/api/v1/verifications` | 上傳正反面照片並同步取得結果 |
| `GET` | `/api/v1/verifications?limit=50&offset=0` | 由新到舊列出核對摘要 |
| `GET` | `/api/v1/verifications/{verification_id}` | 取得完整結果與照片中繼資料 |
| `GET` | `/api/v1/verifications/{verification_id}/images/front` | 取得正面原始照片 |
| `GET` | `/api/v1/verifications/{verification_id}/images/back` | 取得反面原始照片 |

完整欄位、回應與錯誤碼請見 [API 合約](docs/API_CONTRACT.md)。`NEEDS_REVIEW` 表示證據不足或衝突，不可自動視為核對成功。

## 區網存取

即使設定 `OCR_BIND_HOST=0.0.0.0`，主機防火牆仍需允許樹莓派連入 TCP 8000。以下 Windows 範例僅允許目前 `210.240.160.0/24` 網段，請以系統管理員 PowerShell 執行；換網段時調整 `RemoteAddress`：

```powershell
New-NetFirewallRule -DisplayName "MedicServer OCR API (LAN 8000)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress 210.240.160.0/24 -Profile Any
```

在樹莓派測試：

```bash
curl http://210.240.160.159:8000/api/v1/health
```

接著將樹莓派的 `MEDILENS_BACKEND_UPLOAD_URL` 設為：

```text
http://210.240.160.159:8000/api/v1/verifications
```

以上 IP 是目前環境範例，請替換成實際後端主機地址。

## Pair-YOLO／OOD 與 PaddleOCR GPU 模式

GPU 覆寫使用 PaddlePaddle 2.6.2、CUDA 11.2 與 cuDNN 8.2。Windows 請先確認 Docker Desktop 使用 WSL2 後端，且容器能使用 NVIDIA GPU：

```powershell
docker run --rm --gpus all nvidia/cuda:11.2.2-base-ubuntu20.04 nvidia-smi
```

啟動兩個 GPU 推論服務；Pair-YOLO 使用 PyTorch 2.7.1／CUDA 11.8 wheels：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f ocr
curl.exe http://localhost:8000/api/v1/health
```

公開健康回應應包含 `ocr_device: "cuda:0"`、`paddle_cuda: true` 與至少一筆 `cuda_devices`。使用 `OCR_GPU_DEVICE`、`YOLO_GPU_DEVICE` 選擇各容器可見的 GPU 索引。YOLO worker 的 `/health` 包含運算裝置、校準門檻、產物雜湊與 bank 維度；此覆寫為兩服務都預留 NVIDIA GPU。若需 GPU OCR 搭配 CPU YOLO，省略 `yolo` 覆寫，或另建使用 CPU Dockerfile 與裝置的本機覆寫。

切回 CPU：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
docker compose up -d --build
```

## 測試與維護

不載入模型即可執行融合與 HTTP 整合測試；HTTP 的模型／資料庫邊界以 mock 替代：

```powershell
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
python tests/run_upstream_core.py
python tools/verify_deployment.py
```

需要 CPU 服務相依套件，離線部署檢查另需 `PyYAML`。核心回歸測試不載入 Torch、PaddleOCR 模型或資料庫。原始完整測試保留在 `tests/upstream/`；OCR、影像及批次測試仍需各自執行相依套件。離線檢查不代表已完成 Docker／GPU 實測。

檢查模型與初始資料是否遭意外替換：

```powershell
Get-FileHash .\models\best_pair.pt -Algorithm SHA256
Get-FileHash .\models\yolo_best.pt -Algorithm SHA256
Get-Content .\models\SHA256SUMS
```

停止服務：

```powershell
docker compose down
```

除非確定刪除資料，請勿加 `-v` 或刪除 `data/`，以免移除 PostgreSQL、照片、辨識結果與模型快取。`database/init/*.sql` 僅在空 PostgreSQL 資料目錄首次初始化時執行；修改 SQL 不會自動遷移既有資料庫。
