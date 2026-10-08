'use strict';
const { URL } = require('node:url');

function sameOrigin(value, origin) {
  try { return new URL(value).origin === origin; } catch { return false; }
}
function canOpenExternal(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password;
  } catch { return false; }
}
function assertSender(event, window, origin) {
  if (event.sender !== window?.webContents || event.senderFrame !== window.webContents.mainFrame ||
      !sameOrigin(event.senderFrame.url, origin)) throw new Error('Origen de escritorio no autorizado.');
}
// Window controls (minimize/maximize/close) must also work on the local startup page, before the origin exists.
function assertChromeSender(event, window, origin, startupUrl) {
  if (event.sender !== window?.webContents || event.senderFrame !== window.webContents.mainFrame) throw new Error('Origen de escritorio no autorizado.');
  const url = event.senderFrame.url;
  if (!(origin && sameOrigin(url, origin)) && url !== startupUrl) throw new Error('Origen de escritorio no autorizado.');
}
module.exports = { sameOrigin, canOpenExternal, assertSender, assertChromeSender };
