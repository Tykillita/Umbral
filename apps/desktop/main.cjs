'use strict';
const { app, BrowserWindow, ipcMain, session, shell } = require('electron');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { mkdirSync, readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { sameOrigin, canOpenExternal, assertSender } = require('./security.cjs');

let window, child, origin, timer, stopping = false;
const token = randomBytes(32).toString('hex');
const desktopRoot = __dirname;
const resources = app.isPackaged ? process.resourcesPath : path.join(desktopRoot, 'staging');
const bundle = JSON.parse(readFileSync(path.join(resources, 'bundle-manifest.json'), 'utf8'));
const dataDir = path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'Umbral');
mkdirSync(dataDir, { recursive: true });
app.setPath('userData', path.join(dataDir, 'browser'));
app.enableSandbox();
if (!app.requestSingleInstanceLock()) { app.quit(); }
app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.focus(); } });

function sidecarCommand() {
  if (app.isPackaged) return [path.join(resources, 'sidecar', 'umbral-sidecar.exe'), []];
  const built = path.join(desktopRoot, 'dist', 'umbral-sidecar', 'umbral-sidecar.exe');
  return [built, []];
}
function startSidecar() {
  const [command, args] = sidecarCommand();
  child = spawn(command, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    cwd: dataDir, env: { ...process.env, UMBRAL_DESKTOP_RUNTIME: '1', HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1',
      USE_TF: '0', UMBRAL_LAYA_MODEL_DIR: path.join(resources, 'laya') } });
  // The ephemeral credential travels over a private pipe, never process arguments or logs.
  child.stdin.end(JSON.stringify({ token, resources, dataDir, parentPid: process.pid,
    version: app.getVersion(), feedUrl: process.env.UMBRAL_DESKTOP_FEED_URL || bundle.feedUrl,
    publicApiUrl: process.env.UMBRAL_DESKTOP_PUBLIC_API_URL || bundle.publicApiUrl,
    publicConfigUrl: bundle.publicConfigUrl, offline: process.env.UMBRAL_DESKTOP_OFFLINE === '1' }) + '\n');
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('No se pudo iniciar Umbral dentro de 90 segundos.')), 90000);
    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      try {
        const item = JSON.parse(line);
        if (item.type === 'ready' && Number.isInteger(item.port) && item.port > 0 && item.port < 65536) {
          clearTimeout(timeout); resolve(`http://127.0.0.1:${item.port}`);
        }
      } catch { /* sidecar startup diagnostics never enter the UI/logs */ }
    });
    child.on('error', () => { clearTimeout(timeout); reject(new Error('Falta el motor incluido de Umbral.')); });
    child.on('exit', () => { clearTimeout(timeout); if (!origin) reject(new Error('El motor local no pudo arrancar.'));
      else if (!stopping) { window?.webContents.send('umbral:progress', { available: false,
        error: 'El motor local se detuvo. Cierra y vuelve a abrir Umbral.' }); } });
  });
}
async function request(endpoint, method = 'GET') {
  const response = await fetch(`${origin}/api/v1/desktop/${endpoint}`, { method,
    headers: { 'x-umbral-desktop-token': token }, signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(response.status === 409 ? 'Ya hay una tarea de datos en curso.' : 'No se pudo completar la operación local.');
  return response.json();
}
function setupIpc() {
  ipcMain.on('umbral:configuration', (event) => {
    try { assertSender(event, window, origin); event.returnValue = { version: app.getVersion(), apiToken: token }; }
    catch { event.returnValue = { version: app.getVersion(), apiToken: '' }; }
  });
  for (const [channel, endpoint, method] of [['status', 'status', 'GET'], ['reclassify', 'reclassify', 'POST'], ['update', 'update', 'POST']]) {
    ipcMain.handle(`umbral:${channel}`, (event) => { assertSender(event, window, origin); return request(endpoint, method); });
  }
}
async function stop() {
  if (stopping) return;
  stopping = true;
  clearInterval(timer);
  try { if (origin) await request('shutdown', 'POST'); } catch { /* bounded process tree cleanup below */ }
  if (child && child.exitCode === null) {
    await new Promise((resolve) => {
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      killer.on('exit', resolve); killer.on('error', resolve);
    });
  }
}
app.on('before-quit', (event) => { if (!stopping) { event.preventDefault(); stop().finally(() => app.quit()); } });
app.on('window-all-closed', () => app.quit());
app.whenReady().then(async () => {
  BrowserWindow.removeMenu?.();
  window = new BrowserWindow({ width: 1320, height: 900, minWidth: 640, minHeight: 480, show: false,
    title: 'Umbral', backgroundColor: '#f3ead7', autoHideMenuBar: true,
    icon: app.isPackaged ? path.join(resources, 'umbral.ico') : path.join(desktopRoot, '..', 'web', 'public', 'brand', 'umbral-desktop.ico'),
    webPreferences: { preload: path.join(desktopRoot, 'preload.cjs'), contextIsolation: true, sandbox: true,
      nodeIntegration: false, nodeIntegrationInWorker: false, webSecurity: true, webviewTag: false,
      allowRunningInsecureContent: false } });
  window.removeMenu();
  setupIpc();
  window.once('ready-to-show', () => { if (process.env.UMBRAL_DESKTOP_SMOKE !== '1') window.show(); });
  await window.loadFile(path.join(desktopRoot, 'startup.html'));
  try {
    origin = await startSidecar();
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    session.defaultSession.on('will-download', (_event, item) => {
      const directory = process.env.UMBRAL_DESKTOP_SMOKE === '1' ? path.join(dataDir, 'exports') : app.getPath('downloads');
      mkdirSync(directory, { recursive: true });
      const safeName = path.basename(item.getFilename()).replace(/[^\p{L}\p{N}._-]/gu, '_');
      item.setSavePath(path.join(directory, `${Date.now()}-${safeName}`));
    });
    window.webContents.on('will-navigate', (event, url) => { if (!sameOrigin(url, origin)) event.preventDefault(); });
    window.webContents.setWindowOpenHandler(({ url }) => { if (canOpenExternal(url)) void shell.openExternal(url); return { action: 'deny' }; });
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: {
      ...details.responseHeaders, 'Content-Security-Policy': [`default-src 'self'; script-src 'self' ${(bundle.inlineScriptHashes || []).join(' ')}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'self'; form-action 'none'`] } }));
    // The app redirects / to /app; Chromium reports the superseded first navigation as ERR_ABORTED, which is not a failure.
    await window.loadURL(origin).catch((error) => { if (!String(error && error.message).includes('ERR_ABORTED')) throw error; });
    let previousStatus = '';
    timer = setInterval(async () => { try {
      const status = await request('status');
      const serialized = JSON.stringify(status);
      if (serialized !== previousStatus) { previousStatus = serialized; window?.webContents.send('umbral:progress', status); }
    } catch { } }, 1000);
  } catch (error) {
    if (process.env.UMBRAL_DESKTOP_SMOKE === '1') {
      mkdirSync(path.join(dataDir, 'diagnostics'), { recursive: true });
      writeFileSync(path.join(dataDir, 'diagnostics', 'main-error.log'), String(error && error.stack || error), 'utf8');
    }
    // The startup page may already have been replaced by the app; only touch its status line if still present.
    await window.webContents.executeJavaScript(`(() => { const status = document.querySelector('[data-status]'); if (status) status.textContent = ${JSON.stringify(error.message)}; })();`).catch(() => {});
  }
});
