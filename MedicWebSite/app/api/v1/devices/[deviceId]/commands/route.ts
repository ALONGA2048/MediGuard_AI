import type { CommandType, DeviceCommand, LightMode } from "@/lib/api-types";

const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function POST(request: Request, context: { params: Promise<{ deviceId: string }> }) {
  const { deviceId } = await context.params;
  const body = await request.json() as { type?: CommandType; payload?: { lightMode?: LightMode; brightness?: number } };
  if (!body.type) return Response.json({ error: "command_type_required" }, { status: 400 });
  const now = new Date();
  const command: DeviceCommand = {
    commandId: crypto.randomUUID(), deviceId, type: body.type, payload: body.payload ?? {},
    createdAt: now.toISOString(), expiresAt: new Date(now.getTime() + 120_000).toISOString(),
  };
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ error: "device_token_not_configured", message: "請在網站主機設定 RASPBERRY_PI_DEVICE_TOKEN。" }, { status: 503 });
  try {
    const response = await fetch(`${PI_BASE_URL}/api/v1/commands`, {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(command), signal: AbortSignal.timeout(body.type === "capture" ? 120_000 : 8_000), cache: "no-store",
    });
    return Response.json(await response.json(), { status: response.status });
  } catch (error) {
    return Response.json({ error: "raspberry_pi_unreachable", message: `無法連線至樹莓派 ${PI_BASE_URL}`, detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
