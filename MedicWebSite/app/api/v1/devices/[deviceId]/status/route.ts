const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function GET() {
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ online: false, error: "device_token_not_configured" }, { status: 503 });
  try {
    const response = await fetch(`${PI_BASE_URL}/api/v1/status`, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3_000), cache: "no-store",
    });
    const data = await response.json() as Record<string, unknown>;
    return Response.json({ online: response.ok, ...data }, { status: response.status });
  } catch (error) {
    return Response.json({ online: false, error: "raspberry_pi_unreachable", detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
