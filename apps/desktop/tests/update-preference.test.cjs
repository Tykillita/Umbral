'use strict';

const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { readAutoUpdate, saveAutoUpdate } = require('../update-preference.cjs');

test('la preferencia de actualizaciones se guarda, se restaura y rechaza valores inválidos', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-update-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'update-preference.json');

  assert.equal(readAutoUpdate(file), true);
  assert.equal(saveAutoUpdate(file, false), false);
  assert.equal(readAutoUpdate(file), false);
  assert.equal(saveAutoUpdate(file, true), true);
  assert.equal(readAutoUpdate(file), true);
  assert.throws(() => saveAutoUpdate(file, 'sí'), /no válida/);
});

test('un archivo de preferencia dañado vuelve a las actualizaciones automáticas', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-update-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'update-preference.json');
  require('node:fs').writeFileSync(file, '{malformed', 'utf8');

  assert.equal(readAutoUpdate(file), true);
});
