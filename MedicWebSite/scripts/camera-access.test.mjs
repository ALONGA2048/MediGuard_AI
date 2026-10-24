import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/camera-access.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { cameraAvailabilityMessage, cameraFailureMessage } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("HTTP explains missing permission prompt before attempting unavailable camera API", () => {
  assert.match(cameraAvailabilityMessage(false, false), /HTTP.*不會顯示相機權限提示/);
  assert.match(cameraAvailabilityMessage(false, true), /HTTPS/);
  assert.match(cameraAvailabilityMessage(true, false), /不支援即時相機/);
  assert.equal(cameraAvailabilityMessage(true, true), "");
});

test("permission denial, missing device, and occupied camera have different recovery instructions", () => {
  assert.match(cameraFailureMessage({ name: "NotAllowedError" }), /網站設定與手機系統設定/);
  assert.match(cameraFailureMessage({ name: "NotFoundError" }), /找不到可用相機/);
  assert.match(cameraFailureMessage({ name: "NotReadableError" }), /其他 App 使用/);
  assert.match(cameraFailureMessage(new Error("failure")), /拍照／圖片掃碼/);
});
