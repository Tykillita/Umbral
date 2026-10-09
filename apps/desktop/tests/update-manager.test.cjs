const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { mkdtempSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createUpdateManager } = require('../update-manager.cjs');

function setup(isPackaged = true, preferenceFile) {
  const autoUpdater = new EventEmitter();
  autoUpdater.checkForUpdates = async () => { autoUpdater.checkCount = (autoUpdater.checkCount || 0) + 1; };
  autoUpdater.downloadUpdate = async () => { autoUpdater.downloadCount = (autoUpdater.downloadCount || 0) + 1; };
  autoUpdater.quitAndInstall = (...args) => { autoUpdater.installArgs = args; };
  const app = { isPackaged };
  const states = [];
  const manager = createUpdateManager({ app, autoUpdater, publishState: (state) => states.push(state), preferenceFile });
  return { autoUpdater, app, manager, states };
}

test('con automáticas activas busca, descarga e instala al reiniciar', async () => {
  const { autoUpdater, manager, states } = setup();
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(autoUpdater.autoDownload, true);
  assert.equal(autoUpdater.autoInstallOnAppQuit, true);
  assert.equal(autoUpdater.allowPrerelease, false);
  assert.equal(states.at(-1).status, 'checking');
  assert.equal(states.at(-1).autoUpdateEnabled, true);

  autoUpdater.emit('update-available', { version: '0.2.0' });
  assert.equal(manager.getState().status, 'available');
  assert.equal(manager.getState().version, '0.2.0');
  autoUpdater.emit('download-progress', { percent: 36.2 });
  assert.deepEqual(manager.getState(), { status: 'downloading', version: '0.2.0', percent: 36, autoUpdateEnabled: true });
  autoUpdater.emit('update-downloaded', { version: '0.2.0' });
  assert.equal(manager.getState().status, 'downloaded');
  assert.equal(manager.install(), true);
  assert.deepEqual(autoUpdater.installArgs, [false, true]);
  stop();
});

test('un error de red produce un estado recuperable sin mostrar detalles internos', async () => {
  const { autoUpdater, manager, states } = setup();
  autoUpdater.checkForUpdates = async () => { throw new Error('token/private response'); };
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(manager.getState().status, 'error');
  assert.equal(JSON.stringify(states).includes('token/private response'), false);
  assert.equal(manager.install(), false);
  stop();
});

test('no consulta ni instala actualizaciones durante desarrollo', async () => {
  const { autoUpdater, manager } = setup(false);
  autoUpdater.checkForUpdates = () => { throw new Error('no debe ejecutarse'); };
  const stop = manager.start();
  assert.equal(manager.getState().status, 'idle');
  assert.equal(manager.install(), false);
  stop();
});

test('con automáticas desactivadas solo comprueba y no descarga en segundo plano', async (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-update-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const preferenceFile = path.join(directory, 'update-preference.json');
  require('node:fs').writeFileSync(preferenceFile, JSON.stringify({ autoUpdate: false }), 'utf8');
  const { autoUpdater, manager } = setup(true, preferenceFile);
  assert.equal(manager.isEnabled(), false);
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(autoUpdater.autoDownload, false);
  assert.equal(autoUpdater.autoInstallOnAppQuit, false);
  assert.equal(autoUpdater.checkCount, 1);
  assert.equal(autoUpdater.downloadCount || 0, 0);
  autoUpdater.emit('update-available', { version: '0.3.0' });
  assert.equal(manager.getState().status, 'available');
  assert.equal(manager.getState().autoUpdateEnabled, false);
  assert.equal(autoUpdater.downloadCount || 0, 0);
  stop();
});

test('«Actualizar ahora» descarga y luego instala cuando solo está disponible', async () => {
  const { autoUpdater, manager } = setup();
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  autoUpdater.emit('update-available', { version: '0.2.0' });
  assert.equal(manager.updateNow(), true);
  assert.equal(autoUpdater.downloadCount, 1);
  assert.equal(manager.getState().status, 'downloading');
  autoUpdater.emit('download-progress', { percent: 100 });
  autoUpdater.emit('update-downloaded', { version: '0.2.0' });
  assert.deepEqual(autoUpdater.installArgs, [false, true]);
  stop();
});

test('«Actualizar ahora» instala directamente si ya está descargada', async () => {
  const { autoUpdater, manager } = setup();
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  autoUpdater.emit('update-downloaded', { version: '0.2.0' });
  assert.equal(manager.updateNow(), true);
  assert.deepEqual(autoUpdater.installArgs, [false, true]);
  stop();
});

test('activar y desactivar persiste la preferencia y reaplica los ajustes', async (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'umbral-update-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const preferenceFile = path.join(directory, 'update-preference.json');
  const { autoUpdater, manager } = setup(true, preferenceFile);
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(manager.setEnabled(false), false);
  assert.equal(autoUpdater.autoDownload, false);
  assert.equal(manager.getState().autoUpdateEnabled, false);
  assert.equal(JSON.parse(require('node:fs').readFileSync(preferenceFile, 'utf8')).autoUpdate, false);

  const checksBefore = autoUpdater.checkCount;
  assert.equal(manager.setEnabled(true), true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(autoUpdater.autoDownload, true);
  assert.equal(manager.getState().autoUpdateEnabled, true);
  assert.equal(autoUpdater.checkCount, checksBefore + 1);
  assert.equal(JSON.parse(require('node:fs').readFileSync(preferenceFile, 'utf8')).autoUpdate, true);
  stop();
});
