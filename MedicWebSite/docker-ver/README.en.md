# MediGuard Website Docker Deployment

[繁體中文](README.md) | **English**

Package the complete MedicWebSite application, server APIs, and tester entry point into **one image and one container**. The container retains the existing Vinext / Cloudflare Workers local runtime and serves the built `dist`, without a Vite development server. No Cloudflare account or login is required.

The image runs `vite build` with the project's `vite.config.ts` to generate the Worker configuration required by Wrangler. The current `npm run build` targets Vinext Node; Docker uses the build entry point that matches its runtime.

## Quick Start

Install Docker Engine or Docker Desktop using Linux containers, plus Docker Compose v2. From `MedicWebSite/docker-ver`:

```powershell
Copy-Item .env.example .env
# Edit .env: set the Raspberry Pi LAN address and shared token
docker compose up -d --build
docker compose ps
docker compose logs -f website
```

On Linux, copy the configuration with `cp .env.example .env`. The first build requires internet access to download the Node image, system packages, and npm packages.

- Main website: <http://localhost:3000>
- Tester interface: <http://localhost:3001>
- Health endpoint: <http://localhost:3000/api/v1/health>

If you change `WEBSITE_PORT` or `TESTER_PORT` in `.env`, use those host ports. LAN devices use `http://<deployment-host-IP>:3000` / `:3001`; allow the corresponding ports in the host firewall. Compose publishes both entry points by default. The tester interface has no login. Use the top-right language button to switch between Traditional Chinese and English.

## Raspberry Pi and Recognition Backend

Example website configuration:

```dotenv
RASPBERRY_PI_BASE_URL=http://192.168.1.50:5000
RASPBERRY_PI_DEVICE_TOKEN=replace-with-your-shared-token
```

The token must match `MEDILENS_DEVICE_TOKEN` on the Pi. With an empty token, demonstration pages still work, but hardware APIs return 503. Settings are written to environment files inside the container at startup and are excluded from the image build. After editing them, run `docker compose up -d --force-recreate`; rebuilding is unnecessary. Use a single-line token without double quotes.

Inside a container, `localhost` means the container itself. For a separate Raspberry Pi, use its LAN IP. If the hardware service runs on the Docker host, the default `http://host.docker.internal:5000` can be used; the service must listen on an interface reachable from the container.

This container includes the MedicWebSite UI and APIs. Run `raspberry_pi/hardware.py` on the Pi and deploy the `MedicServer` OCR / YOLO / PostgreSQL stack through its existing Compose setup. Set the Pi's `MEDILENS_BACKEND_UPLOAD_URL` to a reachable MedicServer address and `MEDILENS_WEBSITE_ORIGINS` to both deployed website origins. See the [hardware deployment guide](../raspberry_pi/DEPLOY.md).

Mobile live camera access and browser-selected folder writing require trusted HTTPS or localhost on the same device. For a public domain, add an HTTPS reverse proxy that preserves streaming responses and disables buffering for camera previews.

## Updates, Shutdown, and Checks

```powershell
docker compose up -d --build
docker compose logs --tail 100 website
curl.exe http://localhost:3000/api/v1/health
curl.exe http://localhost:3001/api/v1/health
docker compose down
```

Use `curl` instead of `curl.exe` on Linux. The container health check tests both entry points. This prototype has no production website database or persistent accounts. Wrangler state inside the container is temporary and is removed when the container is recreated. Login and some management data remain demonstrations.

## Move to Another Host

For a source build, copy the entire `MedicWebSite` directory. The `docker-ver` build context uses its parent website source directory. Local `node_modules`, generated output, environment files, runtime state, and hardware programs are excluded; `.openai/hosting.json` is retained because the build needs it.

Alternatively, export the built image so the deployment host does not need source code:

```powershell
docker save -o mediguard-website.tar mediguard-website:latest
# Import on the other host
docker load -i mediguard-website.tar
```

Place `compose.yaml` and your configured `.env` together on the deployment host and run `docker compose up -d --no-build`. The image must match the target CPU architecture. For another architecture, use Docker Buildx; for example, from `MedicWebSite`: `docker buildx build --platform linux/arm64 -f docker-ver/Dockerfile -t mediguard-website:latest --load .`.

To run without Compose, execute from `MedicWebSite`:

```powershell
docker build -f docker-ver/Dockerfile -t mediguard-website:latest .
docker run -d --name mediguard-website --init --restart unless-stopped -p 3000:3000 -p 3001:3001 --env-file docker-ver/.env --add-host host.docker.internal:host-gateway mediguard-website:latest
```

With `docker run`, host ports are controlled by `-p`; `WEBSITE_PORT` and `TESTER_PORT` apply only to Compose. Do not commit a token-bearing `.env` or share the container environment files.
