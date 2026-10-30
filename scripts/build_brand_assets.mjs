// Raster outputs are generated from the approved v14 vector master, never upscaled.
import { readFileSync, writeFileSync } from 'node:fs';
import { Resvg } from '@resvg/resvg-js';
const root = new URL('../', import.meta.url);
const navy = '#10161d';
const source = readFileSync(new URL('assets/ottscout-mark.svg', root), 'utf8');
const body = source.replace(/^.*?<svg[^>]*>/s, '').replace(/<\/svg>\s*$/, '');
const svg = (content, w = 1024, h = w) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${content}</svg>\n`;
const place = (x, y, size) => `<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="112 112 800 800">${body}</svg>`;
const icon = svg(`<rect width="1024" height="1024" fill="${navy}"/>${body}`);
function png(markup, width) {
  return new Resvg(markup, { fitTo: { mode: 'width', value: width }, font: { loadSystemFonts: true, defaultFontFamily: 'Arial' } }).render().asPng();
}
writeFileSync(new URL('assets/ottscout-icon.svg', root), icon);
for (const [name, size] of [['ottscout-icon.png', 512], ['ottscout-icon-192.png', 192], ['ottscout-touch-icon.png', 180]]) {
  writeFileSync(new URL(`assets/${name}`, root), png(icon, size));
}
const sizes = [16, 32, 48];
const images = sizes.map(size => png(icon, size));
const directory = Buffer.alloc(6 + sizes.length * 16);
directory.writeUInt16LE(1, 2); directory.writeUInt16LE(sizes.length, 4);
let offset = directory.length;
images.forEach((bytes, i) => {
  const entry = 6 + i * 16;
  directory[entry] = sizes[i]; directory[entry + 1] = sizes[i];
  directory.writeUInt16LE(1, entry + 4); directory.writeUInt16LE(32, entry + 6);
  directory.writeUInt32LE(bytes.length, entry + 8); directory.writeUInt32LE(offset, entry + 12);
  offset += bytes.length;
});
writeFileSync(new URL('favicon.ico', root), Buffer.concat([directory, ...images]));
const social = svg(`<rect width="1200" height="630" fill="${navy}"/>${place(100, 160, 300)}<text x="458" y="315" fill="#e0e8ed" font-family="Arial,sans-serif" font-size="94" font-weight="700">OTT<tspan fill="#8be0c3" font-weight="400">Scout</tspan></text><text x="462" y="377" fill="#aebdc8" font-family="Arial,sans-serif" font-size="29">Find it. Save it. Watch it.</text>`, 1200, 630);
writeFileSync(new URL('assets/ottscout-social.svg', root), social);
writeFileSync(new URL('assets/ottscout-social.png', root), png(social, 1200));
console.log('Generated v14 favicon, home-screen icons and 1200×630 share artwork.');
