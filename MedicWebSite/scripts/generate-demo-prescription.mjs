// Generate a genuine QR matrix with the website's existing ZXing dependency.
// Pipe its JSON to render-demo-prescription.py to render the printable PNG.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { QRCodeWriter, BarcodeFormat, EncodeHintType } = require("@zxing/library");
const prescription = JSON.parse(readFileSync(new URL("../examples/demo-prescription.json", import.meta.url), "utf8"));
const payload = JSON.stringify(prescription);
const matrix = new QRCodeWriter().encode(payload, BarcodeFormat.QR_CODE, 540, 540, new Map([[EncodeHintType.MARGIN, 4]]));
const rows = Array.from({ length: matrix.getHeight() }, (_, y) => Array.from({ length: matrix.getWidth() }, (_, x) => matrix.get(x, y) ? 1 : 0));
process.stdout.write(JSON.stringify({ prescription, rows }));
