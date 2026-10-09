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
function isChatGPTAuthUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'auth.openai.com' && !url.port && !url.username && !url.password;
  } catch { return false; }
}
function publicConnectorApiOrigin(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !/^[a-z0-9][a-z0-9-]*\.onrender\.com$/i.test(url.hostname) || url.port ||
        url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null;
    return url.origin;
  } catch { return null; }
}
function isConnectorRequestPath(value) {
  return typeof value === 'string' && /^\/connectors(?:\/(?:notion(?:\/(?:start|pages|destination|export))?|slack(?:\/(?:start|channels|channel|notifications|share|review-event))?))?$/.test(value);
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
module.exports = { sameOrigin, canOpenExternal, isChatGPTAuthUrl, publicConnectorApiOrigin, isConnectorRequestPath, assertSender, assertChromeSender };
