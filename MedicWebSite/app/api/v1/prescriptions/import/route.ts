export async function POST(request: Request) {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) return Response.json({ error: "multipart_form_data_required" }, { status: 415 });
  // Integration point: store the file, enqueue OCR, and return fields for user review.
  return Response.json({ importId: crypto.randomUUID(), status: "queued", lowConfidenceFields: [], prototype: true }, { status: 202 });
}
