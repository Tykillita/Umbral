// Genera los iconos de la PWA a partir de public/brand/icon-512.png (sin servicios externos).
//   node scripts/gen-pwa-icons.mjs
// - icon-192.png / icon-512.png ya existe: "any" (el logo circular con esquinas transparentes).
// - icon-maskable-512.png: logo al 72 % sobre el azul de tinta, a sangre completa; Android lo recorta en círculo, cuadrado o gota.
// - apple-touch-icon.png (180): iOS rellena la transparencia con negro, así que lleva fondo propio y el logo al 84 %.
// `sharp` llega como dependencia de Astro; se resuelve desde ahí para no añadir otra.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const requireFromAstro = createRequire(createRequire(resolve(root, 'package.json')).resolve('astro/package.json'));
const sharp = requireFromAstro('sharp');

const INK = { r: 0x17, g: 0x23, b: 0x37, alpha: 1 }; // --color-ink
const source = resolve(root, 'public/brand/icon-512.png');
const out = (name) => resolve(root, 'public/brand', name);

async function onSquare(size, scale, name) {
  const inner = Math.round(size * scale);
  const logo = await sharp(source).resize(inner, inner).png().toBuffer();
  await sharp({ create: { width: size, height: size, channels: 4, background: INK } })
    .composite([{ input: logo, gravity: 'centre' }])
    .png({ compressionLevel: 9 })
    .toFile(out(name));
  console.log('escrito', name);
}

await sharp(source).resize(192, 192).png({ compressionLevel: 9 }).toFile(out('icon-192.png'));
console.log('escrito icon-192.png');
await onSquare(512, 0.72, 'icon-maskable-512.png');
await onSquare(180, 0.84, 'apple-touch-icon.png');
