const PI_BASE_URL = (process.env.RASPBERRY_PI_BASE_URL ?? "http://210.240.160.159:5000").replace(/\/$/, "");

export async function GET(request: Request) {
  const token = process.env.RASPBERRY_PI_DEVICE_TOKEN;
  if (!token) return Response.json({ error: "device_token_not_configured" }, { status: 503 });
  const requestedCamera = new URL(request.url).searchParams.get("camera") ?? "1";
  if (!["1", "2"].includes(requestedCamera)) return Response.json({ error: "invalid_camera_id" }, { status: 400 });
  try {
    const upstream = await fetch(`${PI_BASE_URL}/api/v1/preview/stream?camera=${requestedCamera}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    if (!upstream.ok || !upstream.body) return Response.json(await upstream.json(), { status: upstream.status });
    return new Response(upstream.body, { status: 200, headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "multipart/x-mixed-replace; boundary=frame", "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: "raspberry_pi_unreachable", detail: error instanceof Error ? error.message : String(error) }, { status: 502 });
  }
}
