const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function POST(request: Request) {
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ error: "device_token_not_configured", message: "請先設定樹莓派裝置金鑰。" }, { status: 503 });
  try {
    const body = await request.text();
    const response = await fetch(`${PI_BASE_URL}/api/v1/preview/start`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: body || "{}", signal: AbortSignal.timeout(8_000), cache: "no-store",
    });
    return Response.json(await response.json(), { status: response.status });
  } catch (error) {
    return Response.json({ error: "raspberry_pi_unreachable", message: `無法連線至樹莓派 ${PI_BASE_URL}`, detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
