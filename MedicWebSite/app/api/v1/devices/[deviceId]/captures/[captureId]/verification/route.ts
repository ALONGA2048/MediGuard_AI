const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function GET(_request: Request, context: { params: Promise<{ captureId: string }> }) {
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ error: "device_token_not_configured" }, { status: 503 });
  const { captureId } = await context.params;
  if (!/^[0-9a-f-]{36}$/.test(captureId)) return Response.json({ error: "invalid_capture_id" }, { status: 400 });
  try {
    const upstream = await fetch(`${PI_BASE_URL}/api/v1/captures/${captureId}/verification`, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(10_000), cache: "no-store",
    });
    const body = await upstream.text();
    let data: unknown;
    try { data = JSON.parse(body); } catch { data = { error: "invalid_raspberry_pi_response", detail: body.slice(0, 500) }; }
    return Response.json(data, { status: upstream.status, headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    return Response.json({ error: "raspberry_pi_unreachable", detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
