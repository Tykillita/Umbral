'use strict';

const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { readMotionPreference, saveMotionPreference } = require('../motion-preference.cjs');

test('la preferencia de escritorio se guarda, se restaura y rechaza valores inválidos', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-motion-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'motion-preference.json');

  assert.equal(readMotionPreference(file), 'system');
  assert.equal(saveMotionPreference(file, 'full'), 'full');
  assert.equal(readMotionPreference(file), 'full');
  assert.throws(() => saveMotionPreference(file, 'unknown'), /no válida/);
  assert.equal(readMotionPreference(file), 'full');
});

test('un archivo de preferencia dañado vuelve al modo sistema', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-motion-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'motion-preference.json');
  require('node:fs').writeFileSync(file, '{malformed', 'utf8');

  assert.equal(readMotionPreference(file), 'system');
});
