'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const config = ipcRenderer.sendSync('umbral:configuration');
contextBridge.exposeInMainWorld('umbralDesktop', Object.freeze({
  version: config.version,
  platform: 'win32',
  apiToken: config.apiToken,
  getStatus: () => ipcRenderer.invoke('umbral:status'),
  reclassify: () => ipcRenderer.invoke('umbral:reclassify'),
  updateSnapshot: () => ipcRenderer.invoke('umbral:update'),
  onProgress: (callback) => {
    if (typeof callback !== 'function') throw new TypeError('Se necesita una función.');
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('umbral:progress', handler);
    return () => ipcRenderer.removeListener('umbral:progress', handler);
  },
}));
