"use client";

import { useTranslation } from "@/components/language-provider";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { BrowserQRCodeReader, type IScannerControls } from "@zxing/browser";
import { Activity, Camera, Check, ClipboardList, Download, Home, Info, QrCode, ScanLine, ShieldCheck, Upload } from "lucide-react";
import { checkPrediction, parseCheckPrescription, type CheckPrescription } from "@/lib/prescription-check";
import { cameraAvailabilityMessage, cameraFailureMessage } from "@/lib/camera-access";

type Recognition = {
  success?: boolean; status: string; error?: string; message?: string;
  result?: { outcome?: string; fused_result?: { final_prediction?: string }; yolo_result?: { prediction?: string } };
};
const device = "/api/v1/devices/medibox-01";
const lighting = { lightMode: "white", brightness: 85 };

export default function PrescriptionVerification({ onOverview }: { onOverview?: () => void }) {
  const t = useTranslation();

  const [stage, setStage] = useState<"idle" | "scan" | "verify" | "complete">("idle");
  const [prescription, setPrescription] = useState<CheckPrescription | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [preview, setPreview] = useState(false), [session, setSession] = useState(0);
  const [busy, setBusy] = useState(false), [waiting, setWaiting] = useState(false), [attempted, setAttempted] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [cameraIssue, setCameraIssue] = useState("");
  const [cameraReady, setCameraReady] = useState(false), [liveRequested, setLiveRequested] = useState(true), [scanSession, setScanSession] = useState(0);
  const video = useRef<HTMLVideoElement>(null), scanner = useRef<IScannerControls | null>(null);
  const generation = useRef(0), mounted = useRef(true), lock = useRef(false), scanHandled = useRef(false);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false; generation.current += 1; activeRequest.current?.abort(); scanner.current?.stop();
      void fetch(`${device}/preview/stop`, { method: "POST" }).catch(() => undefined);
    };
  }, []);

  function acceptPrescription(text: string) {
    try {
      const parsed = parseCheckPrescription(text);
      scanHandled.current = true; scanner.current?.stop();
      setPrescription(parsed); setChecked([]); setError(""); setNotice(""); setStage("verify");
    } catch (e) { setError(e instanceof Error ? e.message : "無法讀取藥單。"); }
  }

  useEffect(() => {
    if (stage !== "scan" || !video.current) return;
    if (!liveRequested) return;
    const unavailable = cameraAvailabilityMessage(window.isSecureContext, !!navigator.mediaDevices?.getUserMedia);
    let cancelled = false;
    // Publish the camera capability result after this effect is established;
    // ignore it if the user has already left the scanner.
    queueMicrotask(() => {
      if (!cancelled) { setCameraReady(false); setCameraIssue(unavailable); }
    });
    if (unavailable) return () => { cancelled = true; };
    scanHandled.current = false;
    const reader = new BrowserQRCodeReader();
    reader.decodeFromConstraints({ video: { facingMode: { ideal: "environment" } }, audio: false }, video.current, (result, _error, controls) => {
      if (cancelled || scanHandled.current || !result) return;
      try { parseCheckPrescription(result.getText()); } catch (e) { setError(e instanceof Error ? e.message : "無效藥單"); return; }
      controls.stop(); acceptPrescription(result.getText());
    }).then(controls => { if (cancelled || scanHandled.current) controls.stop(); else { scanner.current = controls; setCameraReady(true); } })
      .catch(cameraError => { if (!cancelled && !scanHandled.current) setCameraIssue(cameraFailureMessage(cameraError)); });
    return () => { cancelled = true; scanner.current?.stop(); scanner.current = null; };
  }, [stage, liveRequested, scanSession]);

  function pauseLiveScanner() {
    // Release the live camera before the phone opens its native camera app.
    scanner.current?.stop(); scanner.current = null;
    setLiveRequested(false); setCameraReady(false); setCameraIssue("");
  }

  async function readImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    setError(""); const url = URL.createObjectURL(file);
    try {
      const result = await new BrowserQRCodeReader().decodeFromImageUrl(url);
      if (mounted.current && !scanHandled.current) acceptPrescription(result.getText());
    } catch { if (mounted.current && !scanHandled.current) setError("照片中找不到 QR code，請完整拍入藥單 QR code、保持清晰後重試，或選擇原始藥單 PNG。"); }
    finally { URL.revokeObjectURL(url); event.target.value = ""; }
  }

  async function request(path: string, body?: unknown, signal?: AbortSignal) {
    const response = await fetch(`${device}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal });
    const data = await response.json() as { success?: boolean; message?: string; error?: string; result?: { captureId: string; backendUpload?: { status: string } } };
    if (!response.ok || data.success === false) throw new Error(data.message || data.error || "裝置操作失敗，請確認暗箱連線。");
    return data;
  }

  async function startPreview() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const controller = new AbortController(); activeRequest.current = controller;
    try {
      await request("/preview/start", lighting, AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]));
      if (mounted.current) { setPreview(true); setSession(value => value + 1); setAttempted(false); }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }

  async function captureAndCheck() {
    if (lock.current || !preview || !prescription) return;
    lock.current = true; setBusy(true); setWaiting(true); setError(""); setNotice("");
    const current = ++generation.current;
    const controller = new AbortController(); activeRequest.current = controller;
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(330_000)]);
    try {
      const data = await request("/commands", { type: "capture", payload: lighting }, signal);
      if (!mounted.current || current !== generation.current) return;
      setPreview(false); setAttempted(true);
      if (!data.result?.captureId) throw new Error("裝置未回傳拍攝資訊，請重試。");
      if (data.result.backendUpload?.status === "not_configured") throw new Error("辨識服務尚未設定，請確認 MedicServer 連線。");
      const captureId = data.result.captureId;
      for (let attempt = 0; attempt < 150; attempt++) {
        if (!mounted.current || current !== generation.current) return;
        const response = await fetch(`${device}/captures/${captureId}/verification`, { cache: "no-store", signal });
        const recognition = await response.json() as Recognition;
        if (!mounted.current || current !== generation.current) return;
        if (!response.ok || recognition.success === false) throw new Error(recognition.message || recognition.error || "無法取得辨識狀態，請重試。");
        if (["failed", "not_configured"].includes(recognition.status)) throw new Error(recognition.error || "辨識服務未完成，請確認服務狀態後重試。");
        if (recognition.status === "completed") {
          const result = recognition.result;
          // A fused unknown/review result must never fall back to a YOLO candidate.
          const prediction = result?.fused_result ? result.fused_result.final_prediction : result?.yolo_result?.prediction;
          const match = checkPrediction(prescription, checked, prediction, result?.outcome);
          setChecked(match.checked);
          setNotice(match.kind === "matched" ? "核對成功，已在右側藥單標記。請更換下一項藥品。" : match.kind === "duplicate" ? "這項藥品已核對，請更換尚未核對的藥品。" : "本次未能核對藥單上的藥品，請確認放置的藥品後重試。");
          if (match.checked.length === prescription.medicines.length) setStage("complete");
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      throw new Error("辨識等待超過 5 分鐘，請確認 MedicServer 狀態後重試。");
    } catch (e) { if (mounted.current && current === generation.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { lock.current = false; if (mounted.current && current === generation.current) { setBusy(false); setWaiting(false); } }
  }

  function overview() {
    if (onOverview) onOverview();
    else { setStage("idle"); setPrescription(null); setChecked([]); setAttempted(false); setNotice(""); setError(""); }
  }

  if (stage === "complete") return <section className="panel verification-complete" role="status"><span><ShieldCheck/></span><p className="eyebrow-text">PRESCRIPTION VERIFIED</p><h1>{t("核對成功！")}</h1><p>{t("藥單上的")} {t(prescription?.medicines.length)}  {t("項藥品皆已完成核對。")}</p><div>{prescription?.medicines.map(item => <p key={item.name}><Check/>{t(item.name)}</p>)}</div><button className="primary-btn" onClick={overview}><Home/>{t("返回總覽")}</button></section>;

  return <>
    <div className="page-title"><div><span className="eyebrow-text">MEDICATION VERIFICATION</span><h1>{t("藥物辨識與核對")}</h1><p>{t("掃描藥單 QR code，再逐項核對暗箱中的藥品。")}</p></div><a className="secondary-btn" href="/demo-prescription.png" download><Download/>{t("下載模擬藥單")}</a></div>
    <div className="capture-steps"><span className={stage === "idle" ? "active" : "done"}><i>1</i>{t("啟動辨識")}</span><b/><span className={stage === "scan" ? "active" : stage === "verify" ? "done" : ""}><i>2</i>{t("掃描藥單")}</span><b/><span className={stage === "verify" ? "active" : ""}><i>3</i>{t("逐項核對")}</span></div>
    {stage === "idle" && <section className="panel verification-start"><span><QrCode/></span><h2>{t("先掃藥單，再核對藥品")}</h2><p>{t("準備好藥單與藥品，啟動後可即時掃描或使用手機拍照掃碼。")}</p><button className="primary-btn" onClick={() => { scanHandled.current = false; setLiveRequested(true); setCameraIssue(""); setError(""); setStage("scan"); }}><ScanLine/>{t("啟動辨識")}</button></section>}
    {stage === "scan" && <section className="panel verification-scan"><h2>{t("掃描藥單 QR code")}</h2><p>{t("即時掃描或拍下藥單 QR code，讀取後會自動進入藥品核對。")}</p>
      {cameraIssue && <div className="camera-access-message" role="status"><Info/><p>{t(cameraIssue)}</p></div>}
      <div className="verification-scan-actions"><label className="primary-btn"><Camera/>{t("開啟手機相機拍照掃碼")}<input type="file" accept="image/*" capture="environment" aria-label={t("開啟手機相機拍照掃碼")} onClick={pauseLiveScanner} onChange={readImage}/></label><label className="secondary-btn"><Upload/>{t("選擇藥單圖片")}<input type="file" accept="image/*" aria-label={t("選擇藥單圖片")} onClick={pauseLiveScanner} onChange={readImage}/></label>{!cameraReady && <button className="secondary-btn" onClick={() => { setError(""); setLiveRequested(true); setScanSession(value => value + 1); }}>{t("重新啟動即時掃描")}</button>}<button className="secondary-btn" onClick={() => { scanHandled.current = true; setError(""); setCameraIssue(""); setStage("idle"); }}>{t("取消掃描")}</button></div>
      <div className={`scanner ${cameraReady ? "" : "scanner-inactive"}`}><video ref={video} muted playsInline autoPlay/>{cameraReady ? <span className="scanner-frame"/> : <div className="scanner-placeholder"><Camera/><strong>{t(cameraIssue ? "即時相機目前無法使用" : !liveRequested ? "使用下方拍照或圖片掃碼" : "正在啟動相機…")}</strong><span>{t("也可直接開啟手機相機拍攝 QR code")}</span></div>}</div>
      <p className="camera-capture-note">{t("拍照後按「使用照片」即可讀取 QR code。若未開啟相機，請用手機的 Safari／Chrome 開啟此頁，或選擇已拍好的藥單圖片。")}</p></section>}
    {stage === "verify" && prescription && <div className="verification-grid">
      <section className="panel verification-camera"><div className="camera-view"><div className="viewfinder"><i/><i/><i/><i/></div>{preview ? <><img key={session} className="camera-feed" src={`${device}/preview/stream?camera=1&session=${session}`} alt={t("Cam1 藥品即時預覽")}/><span className="calibration-cross" aria-hidden="true"/></> : <div className="capture-idle"><span>{waiting ? <Activity/> : <Camera/>}</span><strong>{t(waiting ? "正在辨識並核對藥品…" : attempted ? "請繼續辨識下一項藥品" : "藥單已取得，準備核對藥品")}</strong><small>{t("將一項藥品放入暗箱，對準紅色十字")}</small></div>}<span className="camera-label"><Camera/>Cam1</span></div><div className="camera-footer"><span><i/>{t(preview ? "即時預覽" : waiting ? "核對中" : "等待辨識")}</span><span>{t("固定白光・雙角度辨識")}</span></div><div className="verification-controls">{preview ? <button className="capture-btn" disabled={busy} onClick={captureAndCheck}><ScanLine/>{t(busy ? "辨識核對中…" : "辨識並核對")}</button> : <button className="capture-btn" disabled={busy} onClick={startPreview}><Camera/>{t(busy ? waiting ? "辨識核對中…" : "啟動相機中…" : attempted ? "繼續辨識" : "開啟 Cam1")}</button>}<p className="safe-note"><ShieldCheck/>{t("每次放入一項藥品，完成後更換下一項。")}</p></div></section>
      <section className="panel verification-prescription"><div className="panel-head"><div><span className="section-kicker">PRESCRIPTION CHECKLIST</span><h2><ClipboardList/>{t("藥單核對清單")}</h2></div><span className="status verified">{t(checked.length)} / {t(prescription.medicines.length)}</span></div><p className="verification-rx-meta">{t(prescription.clinic)} · {t(prescription.id)}</p><progress aria-label={t("藥單核對進度")} value={t(checked.length)} max={prescription.medicines.length}/><ul>{prescription.medicines.map((item, index) => { const done = checked.includes(item.name); return <li key={item.name} className={done ? "is-checked" : ""}><span className="verification-check">{done ? <Check/> : index + 1}</span><div><strong>{t(item.name)}</strong><small>{t(done ? "核對成功" : "待核對")}</small></div></li>; })}</ul><p className="safe-note">{t("全部項目核對完成後，將自動顯示成功畫面。")}</p></section>
    </div>}
    {notice && <div className="verification-notice" role="status"><Info/>{t(notice)}</div>}
    {error && <div className="device-error" role="alert"><Info/><span><strong>{t("操作未完成")}</strong>{t(error)}</span></div>}
  </>;
}
