import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import ts from "typescript";

const source = readFileSync(new URL("../lib/prescription-check.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { parseCheckPrescription, checkPrediction } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const demo = JSON.parse(readFileSync(new URL("../examples/demo-prescription.json", import.meta.url), "utf8"));

test("QR prescription parsing rejects invalid and duplicate lists", () => {
  assert.deepEqual(parseCheckPrescription(JSON.stringify(demo)), demo);
  for (const value of ["not-json", "null", "{}", '{"medicines":[]}', '{"medicines":[{"name":""}]}', '{"medicines":[{"name":"REXULTI 1mg"},{"name":"rexulti 1 mg"}]}']) assert.throws(() => parseCheckPrescription(value));
});

test("all four drugs can be checked in any order; duplicates do not advance", () => {
  let checked = [];
  for (const name of ["Exelon", "REXULTI 1mg", "Theophyline anhydrous", "Flexer Extended-Release F.C. Tablets 15mg"]) {
    const result = checkPrediction(demo, checked, name, "IDENTIFIED");
    assert.equal(result.kind, "matched"); checked = result.checked;
    const duplicate = checkPrediction(demo, checked, name);
    assert.equal(duplicate.kind, "duplicate"); assert.equal(duplicate.checked.length, checked.length);
  }
  assert.equal(checked.length, 4);
});

test("formatting differences match, while wrong strengths, partial names and review outcomes do not", () => {
  assert.equal(checkPrediction(demo, [], " rexulti_1 mg ").kind, "matched");
  assert.equal(checkPrediction(demo, [], "Flexer Extended Release FC Tablets 15 mg").kind, "matched");
  for (const prediction of [undefined, "unknown", "REXULTI 2mg", "REXULTI", "Exelon 5mg", "Panadol", "Theophylline anhydrous", "Flexer Extended-Release F.C. Tablets 1.5mg", "Flexer Extended-Release F.C. Tablets 1-5mg"]) assert.equal(checkPrediction(demo, [], prediction).kind, "unmatched");
  for (const outcome of ["NEEDS_REVIEW", "MISMATCH"]) assert.equal(checkPrediction(demo, [], "Exelon", outcome).kind, "unmatched");
});

test("the final PNG QR decodes to the exact prescription", () => {
  const require = createRequire(import.meta.url);
  const { RGBLuminanceSource, BinaryBitmap, HybridBinarizer, QRCodeReader } = require("@zxing/library");
  const png = new URL("../public/demo-prescription.png", import.meta.url);
  const python = spawnSync(process.env.PYTHON || "python", ["-c", "from PIL import Image; import sys; im=Image.open(sys.argv[1]).convert('L'); sys.stdout.buffer.write(im.tobytes())", decodeURIComponent(png.pathname).replace(/^\/(\w:)/, "$1")], { maxBuffer: 8 * 1024 * 1024 });
  assert.equal(python.status, 0, python.stderr?.toString() || String(python.error));
  const bitmap = new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(new Uint8ClampedArray(python.stdout), 1440, 1800)));
  assert.deepEqual(JSON.parse(new QRCodeReader().decode(bitmap).getText()), demo);
});
