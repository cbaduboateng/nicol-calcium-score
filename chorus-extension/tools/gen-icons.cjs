/**
 * Generates the extension icons as PNGs with no image dependencies.
 *
 * The mark is three stacked bars: two identical accent-coloured ones and one
 * grey — the repeated-voice idea the tool is built around.
 *
 * Run: node tools/gen-icons.cjs
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(width, height, rgba) {
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0; // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // truecolour with alpha
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function draw(size) {
  const buf = Buffer.alloc(size * size * 4);
  const radius = size * 0.22;

  const set = (x, y, [r, g, b, a]) => {
    if (x < 0 || y < 0 || x >= size || y >= size) return;
    const i = (y * size + x) * 4;
    const alpha = a / 255;
    buf[i] = Math.round(buf[i] * (1 - alpha) + r * alpha);
    buf[i + 1] = Math.round(buf[i + 1] * (1 - alpha) + g * alpha);
    buf[i + 2] = Math.round(buf[i + 2] * (1 - alpha) + b * alpha);
    buf[i + 3] = Math.max(buf[i + 3], a);
  };

  // Rounded-square background.
  const inCorner = (x, y) => {
    const cx = Math.min(x, size - 1 - x);
    const cy = Math.min(y, size - 1 - y);
    if (cx >= radius || cy >= radius) return false;
    const dx = radius - cx;
    const dy = radius - cy;
    return dx * dx + dy * dy > radius * radius;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (!inCorner(x, y)) set(x, y, [22, 24, 28, 255]);
    }
  }

  // Three bars: identical pair in accent red, the odd one out in grey.
  const bars = [
    { widthRatio: 0.56, colour: [209, 52, 75, 255] },
    { widthRatio: 0.56, colour: [209, 52, 75, 255] },
    { widthRatio: 0.34, colour: [138, 148, 166, 255] },
  ];
  const barHeight = Math.max(2, Math.round(size * 0.11));
  const gap = Math.max(2, Math.round(size * 0.075));
  const totalHeight = bars.length * barHeight + (bars.length - 1) * gap;
  const startY = Math.round((size - totalHeight) / 2);
  const startX = Math.round(size * 0.22);

  bars.forEach((bar, index) => {
    const y0 = startY + index * (barHeight + gap);
    const barWidth = Math.round(size * bar.widthRatio);
    for (let y = y0; y < y0 + barHeight; y++) {
      for (let x = startX; x < startX + barWidth; x++) {
        // Round the bar ends.
        const fromEnd = Math.min(x - startX, startX + barWidth - 1 - x);
        const fromEdge = Math.min(y - y0, y0 + barHeight - 1 - y);
        if (fromEnd === 0 && fromEdge === 0) continue;
        set(x, y, bar.colour);
      }
    }
  });

  return buf;
}

const outDir = path.join(__dirname, '..', 'extension', 'icons');
fs.mkdirSync(outDir, { recursive: true });
for (const size of [16, 32, 48, 128]) {
  const file = path.join(outDir, `icon-${size}.png`);
  fs.writeFileSync(file, encodePng(size, size, draw(size)));
  console.log('wrote', path.relative(path.join(__dirname, '..'), file));
}
