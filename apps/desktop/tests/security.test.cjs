const test = require('node:test');
const assert = require('node:assert/strict');
const { sameOrigin, canOpenExternal, assertSender } = require('../security.cjs');
test('IPC sólo admite el frame principal y mismo origen exacto', () => {
  const frame = { url: 'http://127.0.0.1:28121/app' };
  const contents = { mainFrame: frame };
  const window = { webContents: contents };
  assert.doesNotThrow(() => assertSender({ sender: contents, senderFrame: frame }, window, 'http://127.0.0.1:28121'));
  assert.throws(() => assertSender({ sender: contents, senderFrame: { url: frame.url } }, window, 'http://127.0.0.1:28121'));
  assert.equal(sameOrigin('http://localhost:28121', 'http://127.0.0.1:28121'), false);
  assert.equal(sameOrigin('http://127.0.0.1:28122', 'http://127.0.0.1:28121'), false);
});
test('enlaces externos sólo HTTPS sin credenciales ni esquemas ejecutables', () => {
  assert.equal(canOpenExternal('https://www.tvn-2.com/noticias/'), true);
  for (const value of ['file:///C:/Windows', 'javascript:alert(1)', 'http://example.com', 'https://secret@example.com', 'mailto:a@b.com']) {
    assert.equal(canOpenExternal(value), false);
  }
});
