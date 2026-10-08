'use strict';

const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;

function createUpdateManager({ app, autoUpdater, publishState }) {
  let state = { status: 'idle' };
  let interval;
  let checking = false;

  function publish(next) {
    state = next;
    publishState({ ...state });
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
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.allowPrerelease = false;
    autoUpdater.on('checking-for-update', () => publish({ status: 'checking' }));
    autoUpdater.on('update-available', (info) => publish({ status: 'downloading', version: info.version, percent: 0 }));
    autoUpdater.on('update-not-available', () => publish({ status: 'idle' }));
    autoUpdater.on('download-progress', (progress) => publish({
      status: 'downloading', version: state.version, percent: Math.max(0, Math.min(100, Math.round(progress.percent))),
    }));
    autoUpdater.on('update-downloaded', (info) => publish({ status: 'downloaded', version: info.version }));
    autoUpdater.on('error', () => publish({ status: 'error' }));
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

  return { start, check, install, getState: () => ({ ...state }) };
}

module.exports = { CHECK_INTERVAL_MS, createUpdateManager };
