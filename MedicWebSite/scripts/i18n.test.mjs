import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const english = JSON.parse(readFileSync(new URL("../lib/locales/en.json", import.meta.url), "utf8"));
const source = readFileSync(new URL("../lib/i18n.ts", import.meta.url), "utf8")
  .replace('import english from "./locales/en.json";', `const english = ${JSON.stringify(english)};`);
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { translate } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("Chinese display values remain unchanged and English messages are complete", () => {
  for (const [chinese, englishText] of Object.entries(english)) {
    assert.equal(translate(chinese, "zh-Hant"), chinese);
    assert.equal(translate(chinese, "en"), englishText);
    assert.ok(englishText.trim());
    assert.doesNotMatch(englishText, /[\u3400-\u9fff]/);
  }
});

test("camera recovery messages are all translated", () => {
  const source = readFileSync(new URL("../lib/camera-access.ts", import.meta.url), "utf8");
  const file = ts.createSourceFile("camera-access.ts", source, ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isStringLiteral(node) && /[\u3400-\u9fff]/.test(node.text)) {
      assert.notEqual(translate(node.text, "en"), node.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
});

test("dynamic counts and accessible camera labels are translated as full messages", () => {
  assert.equal(translate("下載全部 ZIP（12 張）", "en"), "Download all ZIP (12 photos)");
  assert.equal(translate("刪除第 3 組 Camera 2 照片", "en"), "Delete Camera 2 photo from set 3");
  assert.equal(translate("第 4 項藥品缺少 name", "en"), "Medicine 4 is missing its name");
  assert.equal(translate("無法取得下鏡頭照片", "en"), "Could not retrieve the bottom camera photo");
});

test("external prescription content and non-text values keep their original identity", () => {
  const imported = { clinic: "自訂診所", medicines: [{ name: "REXULTI 1mg" }] };
  assert.equal(translate(imported, "en"), imported);
  assert.equal(translate(imported.clinic, "en"), imported.clinic);
  assert.equal(translate(imported.medicines[0].name, "en"), "REXULTI 1mg");
  assert.equal(translate(4, "en"), 4);
  assert.equal(translate(null, "en"), null);
  assert.equal(translate(" 匯入藥單 ", "en"), " Import prescription ");
});
