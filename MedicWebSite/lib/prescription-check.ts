export type CheckPrescription = { id: string; clinic: string; medicines: { name: string }[] };

// Preserve strengths and formulation words; only formatting may differ.
export function medicineKey(name: string): string {
  return name.normalize("NFKC").toLowerCase()
    // Keep decimal strengths and numeric ranges distinct (1.5mg is not 15mg).
    .replace(/(?<!\d)[.\-/]|[.\-/](?!\d)/g, "")
    .replace(/[\s_\\()[\]{}'"`]+/g, "");
}

export function parseCheckPrescription(text: string): CheckPrescription {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error("QR code 不是有效的藥單 JSON，請掃描模擬藥單上的 QR code。"); }
  if (!value || typeof value !== "object") throw new Error("藥單格式不正確。");
  const raw = value as Record<string, unknown>;
  if (!Array.isArray(raw.medicines) || raw.medicines.length === 0 || raw.medicines.length > 100) throw new Error("藥單必須包含 1 至 100 項藥品。");
  const medicines = raw.medicines.map(item => {
    if (!item || typeof item !== "object" || typeof item.name !== "string" || !item.name.trim() || item.name.length > 200 || !medicineKey(item.name)) throw new Error("藥單內有無效的藥品名稱。");
    return { name: item.name.trim() };
  });
  if (new Set(medicines.map(item => medicineKey(item.name))).size !== medicines.length) throw new Error("藥單有重複藥品，請確認後重新掃描。");
  return { id: typeof raw.id === "string" ? raw.id : "掃碼藥單", clinic: typeof raw.clinic === "string" ? raw.clinic : "掃碼匯入", medicines };
}

export function checkPrediction(prescription: CheckPrescription, checked: string[], prediction?: string, outcome?: string) {
  if (!prediction || ["unknown", "未辨識"].includes(medicineKey(prediction)) || ["NEEDS_REVIEW", "MISMATCH"].includes(outcome || "")) return { kind: "unmatched" as const, checked };
  const medicine = prescription.medicines.find(item => medicineKey(item.name) === medicineKey(prediction));
  if (!medicine) return { kind: "unmatched" as const, checked };
  if (checked.includes(medicine.name)) return { kind: "duplicate" as const, checked };
  return { kind: "matched" as const, checked: [...checked, medicine.name] };
}
