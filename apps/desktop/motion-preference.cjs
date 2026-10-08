'use strict';

const { readFileSync, writeFileSync } = require('node:fs');

const ALLOWED = new Set(['system', 'reduced', 'full']);

function readMotionPreference(filePath) {
  try {
    const value = JSON.parse(readFileSync(filePath, 'utf8')).preference;
    return ALLOWED.has(value) ? value : 'system';
  } catch { return 'system'; }
}

function saveMotionPreference(filePath, preference) {
  if (!ALLOWED.has(preference)) throw new Error('Preferencia de movimiento no válida.');
  writeFileSync(filePath, JSON.stringify({ preference }), 'utf8');
  return preference;
}

module.exports = { readMotionPreference, saveMotionPreference };
