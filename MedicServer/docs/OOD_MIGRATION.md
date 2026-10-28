# drug-project OOD 流程移植

來源：`drug-project` commit `9987e9347360a326cbde4c905ba918001eb28f5c`，2026-10-24。
完整檔案盤點見 `drug-project-file-inventory.csv`；來源及部署檔案 SHA-256 見 `drug-project-sync.json`。

## 流程對照

| 項目 | 舊 Server | 更新後 |
| --- | --- | --- |
| 執行順序 | OCR → 非精確命中才呼叫 YOLO | Pair-YOLO + OOD → OCR/DB → 共識 |
| 特徵 | 分類結果 | 一次 forward 同時產生分類與 Hidden-256 |
| OOD | 無 | cosine kNN1，1046 × 256 feature bank |
| 門檻 | YOLO 0.95 | OOD `< 0.7981438636779785` 拒絕；YOLO final 0.95 |
| OOD 拒絕 | 不適用 | 仍執行 OCR；只有 DB 確認的單一藥名與 YOLO ≥ 0.95 一致才解除 |
| 精確條碼/許可證 | 跳過整個 YOLO | 必須先有合法 OOD 結果；通過後沿用精確識別規則 |
| 未收錄識別碼 | 可能採用 YOLO | 已解碼條碼/許可證查無資料時回傳 UNKNOWN_DRUG |
| 中文通用片段 | 可能把「持續」等算為品牌證據 | 同步新版 matcher，修正 Tamlosin / Tamso_SR 混淆 |
| 失敗 | YOLO 失敗可能仍採用精確 OCR | OOD/服務/DB 錯誤回傳 500 並標記 FAILED |
| GPU | 只有 PaddleOCR | PaddleOCR 與 Pair-YOLO/OOD 各自使用 GPU 映像 |

```text
POST front/back originals
    → yolo service: decode BGR → Pair-YOLO once → cached classification + Hidden-256
                                            → calibrated cosine kNN1
    → ocr service: original files → OCR / ZXing / PostgreSQL
    → REJECT: upstream OCR/YOLO consensus override, else NON_DRUG
      PASS: identifier absence gate → upstream hybrid_decision(cached YOLO)
    → existing API envelope + PostgreSQL JSONB + JSON result file
```

## 移植與部署選擇

- 保留 database / yolo / ocr 三個容器，HTTP 取代原始 multiprocessing queue。Torch 與 Paddle 仍在不同程序；融合階段不再推論一次。每個推論服務維持一個 Uvicorn worker 與序列化鎖。
- `YOLO_STAGE.py`、`realtime_inference.py`、Pair-YOLO、OOD scoring/service/config、資料庫 matching 模組沿用來源程式。HTTP 融合介面直接呼叫上游共識與 hybrid 函式，避免維護另一套規則。
- 原始 runtime 的 OpenCV occupancy/validation 已標記 DISABLED；本次也不加入這些閘門。攝影機控制留在裝置端，不放進 Server。
- Server 原有兩個模型與來源 SHA-256 完全相同，保留 `models/` 檔名。Docker COPY 將它們放到 `ood_filter/config.json` 所要求的 `models/best.pt`、`models/best_pair.pt`，feature bank 原樣打包。上游 OOD 啟動會校驗三份 artifact、checkpoint 結構、類別/鏡頭順序、feature bank 維度。
- CPU 與 GPU Compose 各使用對應 PyTorch wheels（CPU / cu118），GPU override 同時預留兩個服務的 GPU；PaddleOCR 保留既有 CUDA 11.2 映像。每個推論服務設定 `shm_size: 1gb`。
- 保留既有套件版本與 headless OpenCV 的 Server 相容設定；新版來源列出的 Pillow 12.3.0、psycopg2 2.9.13 等版本未全部照抄。OCR 額外保留 Server 原有 `ir_optim=False` 和對 PaddleOCR 2.7.3 的受版本檢查修補。
- `OCR_SUPPORTED_YOLO_THRESHOLD=0.60` 傳入上游函式。實際採用/否決規則由來源函式決定，不在 HTTP 層另行改寫。
- 原 API outcome 不變；非藥品、未收錄藥品與無法確認均維持 `NEEDS_REVIEW`。詳細類型存在 `fused_result.recognition_status`。OOD 與 override 證據存在既有 JSONB 與 JSON，現有資料庫無須重建。

## 發現的來源缺檔

來源 `ocr.py` 引用 `barcode_pipeline`，但整個來源 repository 沒有此檔案；舊 Server 也缺少。新增 Server 專用 `barcode_pipeline.py` 相容模組，使用原始影像呼叫既有 ZXing decoder，只接受 `valid=True` 且通過既有 `valid_barcode_value` 的真實解碼。保留 raw_value、format、BARCODE_DECODED/zxingcpp/decode_success provenance，候選幾何不構成條碼證據。此模組是本次補上的實作，無法宣稱與缺失的原始模組完全等價。

## 驗證與限制

- Server 融合、artifact、條碼相容與 HTTP API 測試：19 個通過。API 測試使用真實 FastAPI 路由；模型與資料庫邊界使用 mock，確認先 OOD 後 OCR、單次 worker 呼叫、錯誤阻擋、OOD 拒絕仍跑共識，以及結果儲存參數。
- 上游核心回歸：30 個通過，直接針對部署的 matching、YOLO_STAGE、scoring 與 realtime helper 執行，包括 Tamlosin 修正與 shared-memory 原圖完整性。
- `tools/verify_deployment.py` 檢查 Python 語法、artifact SHA-256、bank 維度、Dockerfile COPY 來源、CPU/GPU Compose 結構與來源映射。
- 本機沒有 Docker 執行檔、Torch、PaddleOCR 或連線中的測試資料庫，因此未執行 Docker build/up、GPU 推論、完整 46 項原始測試或真實影像端到端辨識。不能把上述離線驗證視為已完成部署。

## 在部署主機啟動

在 `MedicServer` 內保留既有 `.env` 和 `data/`，確認資料庫密碼與 GPU 選擇後執行：

```powershell
# CPU
docker compose config --quiet
docker compose up -d --build

# 或 GPU
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker compose ps
docker compose logs --tail=100 yolo ocr
curl.exe http://localhost:8000/api/v1/health
# 檢查內部 worker 的 OOD metadata
docker compose exec yolo python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8001/health').read().decode())"
```

確認 worker metadata 的 bank_shape 為 `[1046, 256]`、method 為 cosine_knn1、模型 hash 一致，再用已知藥品、非藥品與未收錄藥品的雙面樣本驗證結果。此更新未操作既有容器或清除持久化資料。
