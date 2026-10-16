export async function GET() {
  return Response.json({ status: "ok", service: "medilens-web", mode: "prototype", timestamp: new Date().toISOString() });
}
