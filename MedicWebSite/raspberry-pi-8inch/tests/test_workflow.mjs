import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
const source = readFileSync(new URL('../static/workflow.js', import.meta.url), 'utf8');
const { parseCheckPrescription, checkPrediction } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

const rx = parseCheckPrescription(JSON.stringify({id:'TEST',clinic:'Demo',medicines:[{name:'REXULTI 1mg'},{name:'Exelon'}]}));
test('prescription validation and exact strength matching are retained', () => {
  for (const input of ['null', '{}', '{"medicines":[]}', '{"medicines":[{"name":"A"},{"name":"a"}]}']) assert.throws(() => parseCheckPrescription(input));
  assert.equal(checkPrediction(rx, [], 'rexulti_1 mg', 'IDENTIFIED').kind, 'matched');
  for (const name of ['REXULTI 2mg', 'REXULTI', 'REXULTI 1.5mg']) assert.equal(checkPrediction(rx, [], name).kind, 'unmatched');
});
test('review, mismatch, fused unknown, and duplicates cannot complete a list', () => {
  for (const outcome of ['NEEDS_REVIEW', 'MISMATCH']) assert.equal(checkPrediction(rx, [], 'Exelon', outcome).kind, 'unmatched');
  assert.equal(checkPrediction(rx, [], 'unknown').kind, 'unmatched');
  const first = checkPrediction(rx, [], 'Exelon');
  assert.equal(checkPrediction(rx, first.checked, 'Exelon').kind, 'duplicate');
  assert.equal(checkPrediction(rx, first.checked, 'REXULTI 1mg').checked.length, 2);
});
