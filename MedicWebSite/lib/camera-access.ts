export function cameraAvailabilityMessage(secureContext: boolean, hasMediaDevices: boolean): string {
  if (!secureContext) return "目前使用 HTTP 網址，瀏覽器不會顯示相機權限提示。請改用受信任的 HTTPS 網址進行即時掃描，或按下方「開啟手機相機拍照掃碼」。";
  if (!hasMediaDevices) return "這個瀏覽器不支援即時相機。請用 Safari 或 Chrome 開啟此頁，或使用下方拍照／圖片掃碼。";
  return "";
}

export function cameraFailureMessage(error: unknown): string {
  const name = error && typeof error === "object" && "name" in error ? error.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") return "相機權限遭到封鎖，瀏覽器可能不會再次詢問。請到瀏覽器的網站設定與手機系統設定允許相機，再按「重新啟動即時掃描」。若在 LINE 等 App 內，請改用 Safari／Chrome 開啟。也可直接使用下方拍照掃碼。";
  if (name === "NotFoundError" || name === "DevicesNotFoundError") return "找不到可用相機。請確認手機相機可用，或使用下方圖片掃碼。";
  if (name === "NotReadableError" || name === "TrackStartError") return "相機可能正被其他 App 使用。請關閉其他相機程式後重試，或使用下方拍照掃碼。";
  return "無法啟動即時相機。請改用 Safari／Chrome，或使用下方拍照／圖片掃碼。";
}
