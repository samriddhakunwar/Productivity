/**
 * generate-icons.js
 * Run with Node.js to generate all required PNG icons:
 *   node generate-icons.js
 */

"use strict";

const fs   = require("fs");
const path = require("path");
const { deflateSync } = require("zlib");

const SIZES     = [16, 32, 48, 128];
const ICONS_DIR = path.join(__dirname, "icons");

if (!fs.existsSync(ICONS_DIR)) fs.mkdirSync(ICONS_DIR);

// ─── SVG source ───────────────────────────────────────────────────────────────

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1a1d27"/>
      <stop offset="100%" stop-color="#0f1117"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6c63ff"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <rect width="128" height="128" rx="24" fill="url(#bg)"/>
  <path d="M64 30 C50 30 38 38 36 50 C30 52 26 58 28 66 C24 70 24 78 30 82 C30 90 36 96 44 96 L64 96"
        fill="none" stroke="url(#accent)" stroke-width="3.5" stroke-linecap="round" filter="url(#glow)"/>
  <path d="M64 30 C78 30 90 38 92 50 C98 52 102 58 100 66 C104 70 104 78 98 82 C98 90 92 96 84 96 L64 96"
        fill="none" stroke="url(#accent)" stroke-width="3.5" stroke-linecap="round" filter="url(#glow)"/>
  <line x1="64" y1="30" x2="64" y2="96" stroke="url(#accent)" stroke-width="2" stroke-dasharray="4,4" opacity="0.6"/>
  <circle cx="44" cy="54" r="4" fill="#6c63ff" filter="url(#glow)"/>
  <circle cx="84" cy="54" r="4" fill="#a78bfa" filter="url(#glow)"/>
  <circle cx="40" cy="70" r="3" fill="#6c63ff" filter="url(#glow)"/>
  <circle cx="88" cy="70" r="3" fill="#a78bfa" filter="url(#glow)"/>
  <circle cx="64" cy="63" r="5" fill="url(#accent)" filter="url(#glow)"/>
  <line x1="44" y1="54" x2="64" y2="63" stroke="rgba(108,99,255,0.5)" stroke-width="1.5"/>
  <line x1="84" y1="54" x2="64" y2="63" stroke="rgba(167,139,250,0.5)" stroke-width="1.5"/>
  <path d="M70 14 L62 24 L67 24 L60 36 L74 22 L69 22 Z" fill="#facc15" opacity="0.9" filter="url(#glow)"/>
</svg>`;

fs.writeFileSync(path.join(ICONS_DIR, "icon.svg"), svg);
console.log("✓ Written icons/icon.svg");

// ─── CRC-32 table (must be first, before makeChunk) ───────────────────────────

const crcTable = new Uint32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
  crcTable[n] = c;
}

// ─── Chunk builder ────────────────────────────────────────────────────────────

function makeChunk(type, data) {
  const typeBytes = Buffer.from(type, "ascii");
  const lenBuf    = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);

  let c = 0xffffffff;
  const crcData = Buffer.concat([typeBytes, data]);
  for (let i = 0; i < crcData.length; i++) {
    c = crcTable[(c ^ crcData[i]) & 0xff] ^ (c >>> 8);
  }
  c = (c ^ 0xffffffff) >>> 0;
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(c, 0);

  return Buffer.concat([lenBuf, typeBytes, data, crcBuf]);
}

// ─── Minimal purple PNG builder (zero external deps) ─────────────────────────

function createPurplePNG(size) {
  function u32(n) {
    return Buffer.from([(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff]);
  }

  const sig      = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdrData = Buffer.concat([u32(size), u32(size), Buffer.from([8, 2, 0, 0, 0])]);
  const ihdrChunk = makeChunk("IHDR", ihdrData);

  // Raw image data: filter-byte (0x00) + RGB per row
  const rowBytes = 1 + size * 3;
  const raw      = Buffer.alloc(size * rowBytes);
  for (let row = 0; row < size; row++) {
    const base   = row * rowBytes;
    raw[base]    = 0; // filter: None
    for (let col = 0; col < size; col++) {
      const px   = base + 1 + col * 3;
      raw[px]    = 0x6c; // R
      raw[px+1]  = 0x63; // G
      raw[px+2]  = 0xff; // B
    }
  }
  const idatChunk = makeChunk("IDAT", deflateSync(raw));
  const iendChunk = makeChunk("IEND", Buffer.alloc(0));

  return Buffer.concat([sig, ihdrChunk, idatChunk, iendChunk]);
}

// ─── Generate PNGs ────────────────────────────────────────────────────────────

// Try canvas for high-quality rendering
let createCanvas = null;
try { ({ createCanvas } = require("canvas")); } catch { /* use fallback */ }

if (createCanvas) {
  const { loadImage } = require("canvas");
  const svgB64 = Buffer.from(svg).toString("base64");
  (async () => {
    const img = await loadImage(`data:image/svg+xml;base64,${svgB64}`);
    for (const size of SIZES) {
      const canvas = createCanvas(size, size);
      canvas.getContext("2d").drawImage(img, 0, 0, size, size);
      fs.writeFileSync(path.join(ICONS_DIR, `icon${size}.png`), canvas.toBuffer("image/png"));
      console.log(`✓ icon${size}.png (canvas)`);
    }
    console.log("\n✅ All icons generated via canvas!");
  })();
} else {
  console.log("\n⚠ canvas not found — generating solid-purple placeholders.");
  console.log("  Run `npm install canvas` and re-run for SVG-rendered icons.\n");
  for (const size of SIZES) {
    fs.writeFileSync(path.join(ICONS_DIR, `icon${size}.png`), createPurplePNG(size));
    console.log(`✓ icon${size}.png (placeholder)`);
  }
  console.log("\n✅ Icons ready. Extension will install correctly.");
}
