const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function GET(_request: Request, context: { params: Promise<{ captureId: string; cameraId: string }> }) {
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ error: "device_token_not_configured" }, { status: 503 });
  const { captureId, cameraId } = await context.params;
  if (!/^[0-9a-f-]{36}$/.test(captureId) || !["1", "2"].includes(cameraId)) return Response.json({ error: "invalid_capture_image" }, { status: 400 });
  try {
    const upstream = await fetch(`${PI_BASE_URL}/api/v1/captures/${captureId}/camera/${cameraId}`, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15_000), cache: "no-store",
    });
    if (!upstream.ok || !upstream.body) return Response.json({ error: "capture_image_unavailable" }, { status: upstream.status });
    return new Response(upstream.body, { status: 200, headers: { "Content-Type": "image/jpeg", "Cache-Control": "private, no-store" } });
  } catch (error) {
    return Response.json({ error: "raspberry_pi_unreachable", detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
