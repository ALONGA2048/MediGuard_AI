# MediGuard 網站 Docker 部署

將完整 MedicWebSite 網站、伺服器端 API 與測試入口包成**一個映像檔、一個容器**。保留現有 Vinext / Cloudflare Workers 本機執行方式，使用建置後的 `dist` 啟動，不使用 Vite 開發伺服器。無須 Cloudflare 帳號或登入。

映像透過專案的 `vite.config.ts` 執行 `vite build`，產生 Wrangler 所需的 Worker 設定；目前的 `npm run build` 使用 Vinext Node 目標，Docker 改用與執行環境一致的建置入口。

## 快速啟動

需要 Docker Engine / Docker Desktop（Linux containers）與 Docker Compose v2。在 `MedicWebSite/docker-ver` 執行：

```powershell
Copy-Item .env.example .env
# 編輯 .env：填入樹莓派 LAN 位址與共用 Token
docker compose up -d --build
docker compose ps
docker compose logs -f website
```

Linux 複製設定可使用 `cp .env.example .env`。第一次建置需要連網下載 Node 映像、系統套件與 npm 套件。

- 主網站：<http://localhost:3000>
- 測試介面：<http://localhost:3001>
- 健康檢查：<http://localhost:3000/api/v1/health>

若修改 `.env` 的 `WEBSITE_PORT` 或 `TESTER_PORT`，請使用對應的主機埠。LAN 裝置改用 `http://<部署主機 IP>:3000` / `:3001`，並允許主機防火牆的對應連入埠。Compose 預設對外開放這兩個入口，測試介面目前沒有登入機制。

## 樹莓派與辨識服務

網站設定範例：

```dotenv
RASPBERRY_PI_BASE_URL=http://192.168.1.50:5000
RASPBERRY_PI_DEVICE_TOKEN=replace-with-your-shared-token
```

Token 必須與樹莓派的 `MEDILENS_DEVICE_TOKEN` 相同。留空仍可看展示頁面，但硬體 API 會回覆 503。設定只在啟動時寫入容器內的環境檔，不打包進映像；修改後執行 `docker compose up -d --force-recreate`，無須重新建置。Token 請使用單行且不含雙引號的字串。

`localhost` 在容器內代表容器本身。樹莓派在另一台機器時，請填其 LAN IP；硬體服務在 Docker 主機時可使用預設的 `http://host.docker.internal:5000`，該服務須監聽可從容器連入的介面。

本容器包含 MedicWebSite 的網頁與 API。`raspberry_pi/hardware.py` 仍在樹莓派上執行；`MedicServer` OCR / YOLO / PostgreSQL 仍使用原有 Compose。樹莓派的 `MEDILENS_BACKEND_UPLOAD_URL` 要指向它能連線的 MedicServer 位址，`MEDILENS_WEBSITE_ORIGINS` 則填部署後的兩個網站來源。詳見 [硬體部署指南](../raspberry_pi/DEPLOY.md)。

手機即時相機與瀏覽器選擇資料夾寫入功能需要可信任的 HTTPS 或同一裝置上的 localhost。正式網域可在前方加 HTTPS 反向代理，保留串流回應並關閉相機預覽的代理緩衝。

## 更新、停止與檢查

```powershell
docker compose up -d --build
docker compose logs --tail 100 website
curl.exe http://localhost:3000/api/v1/health
curl.exe http://localhost:3001/api/v1/health
docker compose down
```

Linux 使用 `curl` 代替 `curl.exe`。容器健康檢查會同時檢查兩個入口。此網站目前沒有正式資料庫與持久化帳號；容器內 Wrangler 狀態是暫存資料，重建容器會清除。登入與部分管理資料仍為原專案展示功能。

## 搬到另一台主機

從原始碼建置時，請搬移整個 `MedicWebSite`，`docker-ver` 的 build context 會使用上層網站原始碼。建置會排除本機 `node_modules`、產物、環境檔、執行狀態與硬體程式；保留必要的 `.openai/hosting.json` 建置設定。

也可將已建好的映像匯出，部署主機就不需要原始碼：

```powershell
docker save -o mediguard-website.tar mediguard-website:latest
# 在另一台主機匯入
docker load -i mediguard-website.tar
```

將 `compose.yaml` 與自行設定的 `.env` 放在部署主機的同一資料夾，再執行 `docker compose up -d --no-build`。映像必須與目標主機 CPU 架構相容；跨架構請在建置端使用 Docker Buildx，例如在 `MedicWebSite` 執行 `docker buildx build --platform linux/arm64 -f docker-ver/Dockerfile -t mediguard-website:latest --load .`。

不使用 Compose 時，在 `MedicWebSite` 執行：

```powershell
docker build -f docker-ver/Dockerfile -t mediguard-website:latest .
docker run -d --name mediguard-website --init --restart unless-stopped -p 3000:3000 -p 3001:3001 --env-file docker-ver/.env --add-host host.docker.internal:host-gateway mediguard-website:latest
```

`docker run` 的主機埠由 `-p` 控制；`.env` 中 `WEBSITE_PORT` / `TESTER_PORT` 僅用於 Compose。請勿提交含 Token 的 `.env` 或對外分享容器環境檔。
