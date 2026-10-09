'use strict';

const { readFileSync, writeFileSync } = require('node:fs');

function readAutoUpdate(filePath) {
  try {
    const value = JSON.parse(readFileSync(filePath, 'utf8')).autoUpdate;
    return value === false ? false : true;
  } catch { return true; }
}

function saveAutoUpdate(filePath, enabled) {
  if (typeof enabled !== 'boolean') throw new Error('Preferencia de actualización no válida.');
  writeFileSync(filePath, JSON.stringify({ autoUpdate: enabled }), 'utf8');
  return enabled;
}

module.exports = { readAutoUpdate, saveAutoUpdate };
