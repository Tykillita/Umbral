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
module.exports = { sameOrigin, canOpenExternal, assertSender };
