const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createUpdateManager } = require('../update-manager.cjs');

function setup(isPackaged = true) {
  const autoUpdater = new EventEmitter();
  autoUpdater.checkForUpdates = async () => {};
  autoUpdater.quitAndInstall = (...args) => { autoUpdater.installArgs = args; };
  const app = { isPackaged };
  const states = [];
  const manager = createUpdateManager({ app, autoUpdater, publishState: (state) => states.push(state) });
  return { autoUpdater, app, manager, states };
}

test('busca releases estables, descarga en segundo plano y permite instalar al reiniciar', async () => {
  const { autoUpdater, manager, states } = setup();
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(autoUpdater.autoDownload, true);
  assert.equal(autoUpdater.autoInstallOnAppQuit, true);
  assert.equal(autoUpdater.allowPrerelease, false);
  assert.deepEqual(states.at(-1), { status: 'checking' });

  autoUpdater.emit('update-available', { version: '0.2.0' });
  autoUpdater.emit('download-progress', { percent: 36.2 });
  assert.deepEqual(states.at(-1), { status: 'downloading', version: '0.2.0', percent: 36 });
  autoUpdater.emit('update-downloaded', { version: '0.2.0' });
  assert.deepEqual(manager.getState(), { status: 'downloaded', version: '0.2.0' });
  assert.equal(manager.install(), true);
  assert.deepEqual(autoUpdater.installArgs, [false, true]);
  stop();
});

test('un error de red produce un estado recuperable sin mostrar detalles internos', async () => {
  const { autoUpdater, manager, states } = setup();
  autoUpdater.checkForUpdates = async () => { throw new Error('token/private response'); };
  const stop = manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(manager.getState(), { status: 'error' });
  assert.equal(JSON.stringify(states).includes('token/private response'), false);
  assert.equal(manager.install(), false);
  stop();
});

test('no consulta ni instala actualizaciones durante desarrollo', async () => {
  const { autoUpdater, manager } = setup(false);
  autoUpdater.checkForUpdates = () => { throw new Error('no debe ejecutarse'); };
  const stop = manager.start();
  assert.deepEqual(manager.getState(), { status: 'idle' });
  assert.equal(manager.install(), false);
  stop();
});
