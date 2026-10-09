'use strict';

const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;
const { readAutoUpdate, saveAutoUpdate } = require('./update-preference.cjs');

function createUpdateManager({ app, autoUpdater, publishState, preferenceFile }) {
  let enabled = preferenceFile ? readAutoUpdate(preferenceFile) : true;
  let state = { status: 'idle' };
  let interval;
  let checking = false;
  let installAfterDownload = false;

  function snapshot() {
    return { ...state, autoUpdateEnabled: enabled };
  }
  function publish(next) {
    state = next;
    publishState(snapshot());
  }
  // Automáticas activas: Umbral busca, descarga e instala sola. Inactivas: solo comprueba, sin descargar en segundo plano.
  function applySettings() {
    autoUpdater.autoDownload = enabled;
    autoUpdater.autoInstallOnAppQuit = enabled;
    autoUpdater.allowPrerelease = false;
  }

  async function check() {
    if (!app.isPackaged || checking) return;
    checking = true;
    publish({ status: 'checking' });
    try {
      await autoUpdater.checkForUpdates();
    } catch {
      publish({ status: 'error' });
    } finally {
      checking = false;
    }
  }

  function start() {
    if (!app.isPackaged) return () => {};
    applySettings();
    autoUpdater.on('checking-for-update', () => publish({ status: 'checking' }));
    autoUpdater.on('update-available', (info) => publish({ status: 'available', version: info.version }));
    autoUpdater.on('update-not-available', () => publish({ status: 'idle' }));
    autoUpdater.on('download-progress', (progress) => publish({
      status: 'downloading', version: state.version, percent: Math.max(0, Math.min(100, Math.round(progress.percent))),
    }));
    autoUpdater.on('update-downloaded', (info) => {
      publish({ status: 'downloaded', version: info.version });
      if (installAfterDownload) { installAfterDownload = false; install(); }
    });
    autoUpdater.on('error', () => publish({ status: 'error' }));
    // La comprobación ocurre siempre; la descarga automática depende de la preferencia.
    void check();
    interval = setInterval(() => void check(), CHECK_INTERVAL_MS);
    interval.unref?.();
    return () => clearInterval(interval);
  }

  function install() {
    if (!app.isPackaged || state.status !== 'downloaded') return false;
    autoUpdater.quitAndInstall(false, true);
    return true;
  }

  // «Actualizar ahora»: instala si ya está descargada; si solo está disponible, la descarga y luego instala.
  function updateNow() {
    if (!app.isPackaged) return false;
    if (state.status === 'downloaded') return install();
    if (state.status === 'available') {
      installAfterDownload = true;
      publish({ status: 'downloading', version: state.version, percent: 0 });
      Promise.resolve(autoUpdater.downloadUpdate()).catch(() => {
        installAfterDownload = false;
        publish({ status: 'error' });
      });
      return true;
    }
    return false;
  }

  function setEnabled(next) {
    enabled = next === true;
    if (preferenceFile) saveAutoUpdate(preferenceFile, enabled);
    applySettings();
    publish({ ...state });
    if (enabled) void check();
    return enabled;
  }

  return { start, check, install, updateNow, setEnabled, isEnabled: () => enabled, getState: () => snapshot() };
}

module.exports = { CHECK_INTERVAL_MS, createUpdateManager };
