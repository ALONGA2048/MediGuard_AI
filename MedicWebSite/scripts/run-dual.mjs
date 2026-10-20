import { spawn } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { fileURLToPath } from "node:url";

const mode = process.argv[2] ?? "dev";
if (!new Set(["dev", "start"]).has(mode)) {
  throw new Error("Expected dev or start.");
}

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const mainPort = 3000;
const testerPort = 3001;
const mainArgs = mode === "dev"
  ? ["scripts/run-framework.mjs", "dev", "--port", String(mainPort), "--hostname", "0.0.0.0"]
  : [
      "--import", "./scripts/sites-env.mjs",
      "./node_modules/wrangler/bin/wrangler.js", "dev",
      "--config", "dist/server/wrangler.json",
      "--env-file", fileURLToPath(new URL("../.env", import.meta.url)),
      "--env-file", fileURLToPath(new URL("../.env.local", import.meta.url)),
      "--local", "--persist-to", ".wrangler/state",
      "--ip", "0.0.0.0", "--port", String(mainPort), "--inspector-port", "0",
    ];

const main = spawn(process.execPath, mainArgs, {
  cwd: projectRoot,
  env: process.env,
  stdio: "inherit",
});

function proxyHeaders(headers) {
  const forwardedHost = headers.host ?? `127.0.0.1:${testerPort}`;
  return {
    ...headers,
    host: `127.0.0.1:${mainPort}`,
    "x-forwarded-host": forwardedHost,
    "x-forwarded-proto": "http",
    "x-medigard-entry": "tester",
  };
}

const proxy = http.createServer((request, response) => {
  const upstream = http.request({
    hostname: "127.0.0.1",
    port: mainPort,
    path: request.url,
    method: request.method,
    headers: proxyHeaders(request.headers),
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on("error", (error) => {
    if (!response.headersSent) {
      response.writeHead(503, { "Content-Type": "text/plain; charset=utf-8", "Retry-After": "1" });
    }
    response.end(`MediGuard 主服務尚未就緒：${error.message}`);
  });
  request.pipe(upstream);
});

proxy.on("upgrade", (request, socket, head) => {
  const upstream = net.connect(mainPort, "127.0.0.1", () => {
    const headers = proxyHeaders(request.headers);
    const lines = [`${request.method} ${request.url} HTTP/${request.httpVersion}`];
    for (const [name, value] of Object.entries(headers)) {
      if (Array.isArray(value)) {
        for (const item of value) lines.push(`${name}: ${item}`);
      } else if (value !== undefined) {
        lines.push(`${name}: ${value}`);
      }
    }
    upstream.write(`${lines.join("\r\n")}\r\n\r\n`);
    if (head.length) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on("error", () => socket.destroy());
});

proxy.listen(testerPort, "0.0.0.0", () => {
  console.log(`\nMediGuard 正式網站：http://127.0.0.1:${mainPort}`);
  console.log(`MediGuard 測試介面：http://127.0.0.1:${testerPort}\n`);
});

let shuttingDown = false;
function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  proxy.close();
  if (!main.killed) main.kill("SIGTERM");
  setTimeout(() => process.exit(exitCode), 300).unref();
}

proxy.on("error", (error) => {
  console.error(`無法啟動測試介面 3001：${error.message}`);
  shutdown(1);
});
main.on("error", (error) => {
  console.error(`無法啟動 MediGuard 主服務：${error.message}`);
  shutdown(1);
});
main.on("exit", (code) => shutdown(code ?? 1));
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
