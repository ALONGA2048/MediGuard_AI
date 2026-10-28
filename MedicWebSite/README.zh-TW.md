# MediGuard 智慧用藥守護平台

**繁體中文** | [English](README.md)

MedicWebSite 是 MediGuard AI 的使用者介面與裝置代理層。提供藥物管理畫面，將樹莓派共用 Token 保留在伺服器端，代理鏡頭、燈光、原始照片與 MedicServer 辨識狀態請求。

> 目前為互動原型。樹莓派拍攝與 MedicServer 辨識流程已實作，但登入、藥單、藥品目錄與部分管理資料仍為前端展示或模擬 API，尚未實作正式帳號、授權及持久化。

## 介面語言

登入頁、主網站與測試介面右上角均有 **English / 繁體中文** 按鈕。可即時切換語言，瀏覽器會記住選擇，重新整理後仍生效。介面、展示資料、對話框與相機提示會翻譯顯示；匯入藥單的內容與辨識核對資料保留原值。翻譯維護於 `lib/locales/en.json` 與 `lib/i18n.ts`。

## 已實作功能

- 響應式登入、側邊選單與總覽。
- 藥單列表、即時搜尋、狀態篩選、藥品明細與 JSON 匯入。
- 手機 QR code／條碼藥單匯入。
- 藥品成分、適應症、許可證與注意事項查詢。
- 低頻寬 Cam1 定位預覽、紅色中心十字與同步高解析雙鏡頭拍攝。
- 不將裝置 Token 暴露給瀏覽器的同源樹莓派代理 API。
- 掃描藥單 QR code，將每項藥品放至 Cam1 核對；全部符合才顯示成功。
- 一個啟動指令同時提供 `3000` 完整網站與 `3001` 測試介面。
- 測試介面提供可調燈色／亮度、僅本機拍攝及照片暫存與 ZIP 匯出，不上傳 MedicServer。
- 辨識紀錄、裝置狀態與系統設定。
- `/api/v1` 健康檢查、藥品搜尋、藥單匯入及裝置代理 API。

仍屬原型的部分：

- 登入僅變更前端狀態，沒有正式 session 或角色授權。
- 藥單、藥品與多數管理資料來自本機展示資料。
- `GET /api/v1/drugs` 使用小型模擬目錄。
- `POST /api/v1/prescriptions/import` 回傳模擬排隊工作，不保存檔案或執行 OCR。
- `db/schema.ts` 尚未定義正式應用資料表。

## 資料流程

```text
瀏覽器
  └─> MedicWebSite /api/v1/devices/...（伺服器端代理）
        └─> 樹莓派 :5000
              ├─> Cam1 預覽
              ├─> Cam1／Cam2 拍攝與本機保存
              └─> 背景上傳 front_image／back_image 至 MedicServer :8000
                    └─> OCR + YOLO 融合結果
```

網站每兩秒輪詢該次拍攝的 `verification.json`，最多等待五分鐘。樹莓派 Token 僅存在網站伺服器端的環境設定。

## 藥單核對展示

開啟 **藥物辨識 → 啟動辨識**，允許相機並掃描 `public/demo-prescription.png`。也可使用 **開啟手機相機拍照掃碼** 或 **選擇藥單圖片**。拍照後確認使用照片即可匯入 QR；是否能開啟原生相機取決於手機瀏覽器，App 內建瀏覽器無法開啟時請改用 Safari／Chrome 或選擇既有圖片。QR 內含完整 JSON，不依賴外部網址。

即時相機需要安全來源：可信任 HTTPS，或同一裝置上的 localhost。手機連到 `http://<電腦-IP>:3000` 並非安全來源，瀏覽器會阻擋即時相機且不顯示權限提示。掃描器會先偵測此情況，提示拍照或圖片替代方式。權限遭拒、無相機、相機被占用各有對應說明，調整設定後可重試。選擇拍照時會釋放即時鏡頭，避免占用手機相機。調整允許來源無法讓 HTTP 取得即時相機權限；需部署手機信任憑證的 HTTPS。

匯入後，桌面版左側為 Cam1 與辨識按鈕，右側為藥單清單；手機改為上下排列。開啟 Cam1，放入一項藥品並按 **辨識並核對**。網站以完成的融合預測核對正規化後的完整名稱：可忽略大小寫、空白與分隔符號，但劑量與劑型必須符合。不會將候選、未知、待人工檢視、藥單以外或重複藥品標記成功。按 **繼續辨識** 開啟下一項預覽，四項皆成功後顯示 **核對成功！ → 返回總覽**。此流程不展示拍攝結果及預測藥名；`3001` 的拍照測試工具仍展示照片。

示範藥單保留原名稱：REXULTI 1mg、Theophyline anhydrous、Exelon、Flexer Extended-Release F.C. Tablets 15mg。列印清單與 QR 均以 `examples/demo-prescription.json` 為來源；此為測試文件，不包含醫療用藥指示。

使用 Node、Python／Pillow 重新產生 PNG，並驗證解析、名稱符合、重複、錯誤劑量與 QR 解碼：

```powershell
node scripts/generate-demo-prescription.mjs | python scripts/render-demo-prescription.py
node --test scripts/prescription-check.test.mjs
```

Python 不在 PATH 時，測試可設定 `PYTHON` 指向執行檔。渲染器目前使用 Windows 微軟正黑體。

## 技術與資料夾配置

- React 19、Next.js 16 路由慣例、Vinext、Vite 8。
- Cloudflare Workers 與 Wrangler 執行環境。
- Tailwind CSS 4、shadcn 元件與 Lucide 圖示。
- 已包含 Drizzle ORM 工具，但尚未建立正式 schema。

```text
app/page.tsx          主介面與展示資料
app/api/v1/           網站 API 與樹莓派伺服器代理
components/ui/        共用 UI 元件
components/language-provider.tsx  語言狀態與切換按鈕
lib/locales/en.json   英文翻譯
db/                   Drizzle 入口與 schema
docs/                 網站、樹莓派與 MedicServer 合約
examples/             藥單 JSON 等範例
raspberry_pi/         Flask 硬體服務、環境範本與 systemd 單元
scripts/              開發、建置、Sites 與 Wrangler 工具
docker-ver/           網站單容器部署設定
```

## 環境需求

- Node.js `22.13.0` 以上、npm；專案附 `package-lock.json`。
- 硬體功能需要網站主機能連至樹莓派 Flask 服務。
- 完整辨識需要樹莓派能連至 MedicServer 核對 API。

## 本機開發與 Docker 部署

```powershell
Copy-Item .env.example .env.local
npm install
npm run dev
```

網站單容器部署請參閱 [Docker 說明](docker-ver/README.md)，設定集中於 `docker-ver/`，以上層網站原始碼作為建置 context。

- `http://127.0.0.1:3000/`：完整網站；目前登入為展示，輸入電子郵件與密碼即可。
- `http://127.0.0.1:3001/`：不含登入、藥單、藥品查詢的測試介面，包含辨識流程及獨立拍照測試。

本機拍攝模式使用 `sendToServer: false`，不送至 MedicServer。拍攝照片先保留於瀏覽器暫存清單，可刪除單張或整組，再下載全部 ZIP；重新整理或關閉分頁前請先下載。瀏覽器選擇資料夾等權限仍受安全來源與瀏覽器支援限制。

本機正式啟動（`npm start`／`npm run start:main`）依序讀取網站根目錄 `.env`、`.env.local`，後者優先。目前區網範例主機為 `210.240.160.159`，網站埠 `3000`／`3001`、硬體 `5000`、辨識 `8000`；部署時請使用實際位址。辨識上傳網址在樹莓派另行設定。

| 變數 | 用途 |
| --- | --- |
| `RASPBERRY_PI_BASE_URL` | 樹莓派硬體地址，例如 `http://210.240.160.159:5000` |
| `RASPBERRY_PI_DEVICE_TOKEN` | 與樹莓派 `MEDILENS_DEVICE_TOKEN` 完全相同的長隨機字串 |
| `MEDIGUARD_ALLOWED_DEV_ORIGINS` | 允許載入 Vinext 開發資源的主機名稱／IP，以逗號分隔，例如 `210.240.160.159` |

未設定 Token 時仍可查看展示，但裝置代理回傳 `503 device_token_not_configured`。

### 區網存取

`npm run dev` 預設監聽所有介面。主機防火牆允許 TCP 3000、3001 後，區網可使用 `http://<網站主機-IP>:3000`／`:3001`。手機掃碼與直接選擇資料夾寫入需 HTTPS 或瀏覽器認可的 localhost，普通 HTTP 區網位址可能被拒絕。

## 完整硬體與辨識設定

1. 依 [樹莓派部署指南](raspberry_pi/DEPLOY.md) 啟動 `hardware.py`。
2. 網站 `.env.local` 與樹莓派 `.env` 使用相同 Token。
3. 樹莓派 `MEDILENS_WEBSITE_ORIGINS` 填入兩個網站來源，例如 `http://210.240.160.159:3000,http://210.240.160.159:3001`。
4. `MEDILENS_BACKEND_UPLOAD_URL` 設為 MedicServer，例如 `http://210.240.160.159:8000/api/v1/verifications`。
5. 拍攝前檢查樹莓派與 MedicServer 健康狀態：

```bash
curl http://210.240.160.159:5000/api/v1/health
curl http://210.240.160.159:8000/api/v1/health
```

`210.240.160.x` 是區網範例，請替換實際地址。Cam1 一律對應 `front_image`，Cam2 一律對應 `back_image`。

## 指令與驗證

| 指令 | 用途 |
| --- | --- |
| `npm run dev` | 同時啟動 `0.0.0.0:3000` 網站與 `0.0.0.0:3001` 測試代理 |
| `npm run dev:main` | 僅啟動 3000 主網站 |
| `npm run lint` | ESLint 檢查 |
| `node node_modules\typescript\bin\tsc --noEmit` | TypeScript 型別檢查 |
| `npm run build` | Vinext Node 目標建置 |
| `node node_modules\vite\bin\vite.js build` | 產生 Wrangler Worker 部署建置 |
| `npm start` | 啟動建置後的網站 3000 與測試代理 3001 |

現有 Wrangler 啟動流程請使用相符的 Worker 建置：

```powershell
npm run lint
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
npm start
```

## 網站 API

語言與相機提示回歸測試：`node --test scripts/i18n.test.mjs scripts/camera-access.test.mjs`。

| 方法 | 路徑 | 狀態／用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 網站健康狀態 |
| `GET` | `/api/v1/drugs?q=...` | 使用模擬目錄的原型藥品搜尋 |
| `POST` | `/api/v1/prescriptions/import` | 回傳模擬排隊工作的原型匯入 |
| `GET` | `/api/v1/devices/{deviceId}/status` | 代理樹莓派狀態 |
| `POST` | `/api/v1/devices/{deviceId}/preview/start` | 開燈與啟動 Cam1 預覽 |
| `POST` | `/api/v1/devices/{deviceId}/preview/stop` | 停止預覽並關閉受控燈光 |
| `GET` | `/api/v1/devices/{deviceId}/preview/stream?camera=1\|2` | MJPEG 預覽，預設 Cam1 |
| `POST` | `/api/v1/devices/{deviceId}/commands` | 代理 `set_light`、`capture`、`shutdown_lights` |
| `GET` | `/api/v1/devices/{deviceId}/captures/{captureId}/camera/{cameraId}` | 已保存 Cam1／Cam2 JPEG |
| `GET` | `/api/v1/devices/{deviceId}/captures/{captureId}/verification` | 拍攝的辨識狀態與結果 |

完整請求、回應與安全邊界請見 [API 合約](docs/API_CONTRACT.md)，桌面 JSON 匯入請見 [藥單範例](examples/sample-prescription.json)。

## 後續方向

1. 正式 session、角色與裝置授權。
2. 使用者、裝置、藥單、藥品、照片與稽核資料表。
3. TFDA 同步與真正的藥單 OCR 工作佇列。
4. `NEEDS_REVIEW`、`MISMATCH` 的人工檢視與更正流程。
5. 藥單、影像、裝置祕密的加密、保存期限、刪除、流量限制與金鑰輪替。
