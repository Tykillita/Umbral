'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const config = ipcRenderer.sendSync('umbral:configuration');
contextBridge.exposeInMainWorld('umbralDesktop', Object.freeze({
  version: config.version,
  platform: 'win32',
  apiToken: config.apiToken,
  motionPreference: ipcRenderer.sendSync('umbral:motion-preference:get'),
  setMotionPreference: (preference) => ipcRenderer.invoke('umbral:motion-preference:set', preference),
  openChatGPTAuth: (url) => ipcRenderer.invoke('umbral:open-chatgpt-auth', url),
  requestConnector: (request) => ipcRenderer.invoke('umbral:connector-request', request),
  getStatus: () => ipcRenderer.invoke('umbral:status'),
  reclassify: () => ipcRenderer.invoke('umbral:reclassify'),
  updateSnapshot: () => ipcRenderer.invoke('umbral:update'),
  getUpdateState: () => ipcRenderer.invoke('umbral:update:state'),
  checkForUpdates: () => ipcRenderer.invoke('umbral:update:check'),
  installUpdate: () => ipcRenderer.invoke('umbral:update:install'),
  updateNow: () => ipcRenderer.invoke('umbral:update:now'),
  autoUpdateEnabled: ipcRenderer.sendSync('umbral:update:preference:get'),
  setAutoUpdateEnabled: (enabled) => ipcRenderer.invoke('umbral:update:preference:set', enabled),
  onUpdateState: (callback) => {
    if (typeof callback !== 'function') throw new TypeError('Se necesita una función.');
    const handler = (_event, state) => callback(state);
    ipcRenderer.on('umbral:update:state', handler);
    return () => ipcRenderer.removeListener('umbral:update:state', handler);
  },
  onDownloadStatus: (callback) => {
    if (typeof callback !== 'function') throw new TypeError('Se necesita una función.');
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('umbral:download-status', handler);
    return () => ipcRenderer.removeListener('umbral:download-status', handler);
  },
  windowControls: Object.freeze({
    minimize: () => ipcRenderer.invoke('umbral:window', 'minimize'),
    toggleMaximize: () => ipcRenderer.invoke('umbral:window', 'toggle-maximize'),
    close: () => ipcRenderer.invoke('umbral:window', 'close'),
    getState: () => ipcRenderer.invoke('umbral:window', 'state'),
    onStateChange: (callback) => {
      if (typeof callback !== 'function') throw new TypeError('Se necesita una función.');
      const handler = (_event, state) => callback(state);
      ipcRenderer.on('umbral:window-state', handler);
      return () => ipcRenderer.removeListener('umbral:window-state', handler);
    },
  }),
  onProgress: (callback) => {
    if (typeof callback !== 'function') throw new TypeError('Se necesita una función.');
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('umbral:progress', handler);
    return () => ipcRenderer.removeListener('umbral:progress', handler);
  },
}));
