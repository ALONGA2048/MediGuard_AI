const catalog = [
  { id: "TFDA-012345", licenseNumber: "衛署藥製字第 012345 號", nameZh: "普拿疼膜衣錠 500 毫克", ingredient: "Acetaminophen 500mg", source: "TFDA" },
  { id: "TFDA-024681", licenseNumber: "衛署藥製字第 024681 號", nameZh: "胃舒平錠", ingredient: "Aluminum Hydroxide", source: "TFDA" },
];

export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q")?.toLowerCase() ?? "";
  const items = catalog.filter((drug) => `${drug.nameZh}${drug.ingredient}${drug.licenseNumber}`.toLowerCase().includes(q));
  return Response.json({ items, total: items.length, sourceUpdatedAt: "2026-10-01", prototype: true });
}
