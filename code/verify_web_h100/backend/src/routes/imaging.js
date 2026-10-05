import fs from "fs";
import { deflateSync } from "node:zlib";
import { Router } from "express";
import { resolveRawNpy } from "../data/rawPatients.js";

const router = Router();
const MAX_PREVIEW_SIDE = 640;

function npyHeader(filePath) {
  const fd = fs.openSync(filePath, "r");
  try {
    const prefix = Buffer.alloc(65_536);
    const bytesRead = fs.readSync(fd, prefix, 0, prefix.length, 0);
    if (bytesRead < 12 || prefix.toString("latin1", 0, 6) !== "\x93NUMPY") {
      throw new Error("raw.npy không phải định dạng NPY hợp lệ");
    }
    const major = prefix[6];
    const headerLength = major === 1 ? prefix.readUInt16LE(8) : prefix.readUInt32LE(8);
    const headerStart = major === 1 ? 10 : 12;
    const headerEnd = headerStart + headerLength;
    if (headerEnd > bytesRead) throw new Error("Header NPY vượt giới hạn đọc");
    const text = prefix.toString("latin1", headerStart, headerEnd);
    const descriptor = text.match(/['"]descr['"]\s*:\s*['"]([^'"]+)['"]/)?.[1];
    const shapeText = text.match(/['"]shape['"]\s*:\s*\(([^)]*)\)/)?.[1];
    const fortran = /['"]fortran_order['"]\s*:\s*True/.test(text);
    const shape = shapeText?.split(",").map((value) => Number.parseInt(value.trim(), 10)).filter(Number.isFinite) || [];
    if (!descriptor || ![2, 3].includes(shape.length) || fortran || shape.some(n => !Number.isSafeInteger(n) || n <= 0)) throw new Error("Định dạng NPY chưa được hỗ trợ");
    return { fd, descriptor, shape, dataOffset: headerEnd };
  } catch (error) {
    fs.closeSync(fd);
    throw error;
  }
}

function descriptorInfo(descriptor) {
  const formats = {
    "|u1": [1, (buffer, offset) => buffer.readUInt8(offset)],
    "<u1": [1, (buffer, offset) => buffer.readUInt8(offset)],
    "|i1": [1, (buffer, offset) => buffer.readInt8(offset)],
    "<i1": [1, (buffer, offset) => buffer.readInt8(offset)],
    "<u2": [2, (buffer, offset) => buffer.readUInt16LE(offset)],
    "<i2": [2, (buffer, offset) => buffer.readInt16LE(offset)],
    "<f4": [4, (buffer, offset) => buffer.readFloatLE(offset)],
    "<f8": [8, (buffer, offset) => buffer.readDoubleLE(offset)],
  };
  const info = formats[descriptor];
  if (!info) throw new Error(`dtype NPY chưa được hỗ trợ: ${descriptor}`);
  return { bytesPerValue: info[0], readValue: info[1] };
}

export function buildSlicePreview({ npyPath, meta }, requestedSlice, options = {}) {
  const header = npyHeader(npyPath);
  try {
    const { bytesPerValue, readValue } = descriptorInfo(header.descriptor);
    const [depth, height, width] = header.shape.length === 2
      ? [1, header.shape[0], header.shape[1]]
      : [header.shape.at(-3), header.shape.at(-2), header.shape.at(-1)];
    const parsedSlice = Number.parseInt(requestedSlice, 10);
    const slice = Math.max(0, Math.min(depth - 1, Number.isFinite(parsedSlice) ? parsedSlice : Math.floor(depth / 2)));
    const sourceLength = height * width * bytesPerValue;
    if (sourceLength > 256 * 1024 * 1024 || height > 8192 || width > 8192) throw new Error("Lát ảnh vượt giới hạn kích thước");
    if (fs.fstatSync(header.fd).size !== header.dataOffset + depth * sourceLength) throw new Error("Kích thước NPY không khớp header");
    const source = Buffer.allocUnsafe(sourceLength);
    if (fs.readSync(header.fd, source, 0, sourceLength, header.dataOffset + slice * sourceLength) !== sourceLength) throw new Error("Không đọc đủ pixel của lát ảnh");

    const maxSide = options.resolution === "original" ? 8192 : MAX_PREVIEW_SIDE;
    const scale = Math.max(width, height) / maxSide;
    const previewWidth = Math.max(1, Math.round(width / Math.max(1, scale)));
    const previewHeight = Math.max(1, Math.round(height / Math.max(1, scale)));
    const pixels = Buffer.allocUnsafe(previewWidth * previewHeight);
    const modality = String(meta.Modality || "").toUpperCase();
    const slope = Number.parseFloat(meta.RescaleSlope) || 1;
    const intercept = Number.parseFloat(meta.RescaleIntercept) || 0;
    const values = new Float64Array(previewWidth * previewHeight);
    let min = Infinity;
    let max = -Infinity;
    for (let y = 0; y < previewHeight; y += 1) {
      const sourceY = Math.min(height - 1, Math.floor((y + 0.5) * height / previewHeight));
      for (let x = 0; x < previewWidth; x += 1) {
        const sourceX = Math.min(width - 1, Math.floor((x + 0.5) * width / previewWidth));
        const raw = readValue(source, (sourceY * width + sourceX) * bytesPerValue);
        const value = modality === "CT" && !meta.rescaled ? raw * slope + intercept : raw;
        if (!Number.isFinite(value)) throw new Error("Pixel không hữu hạn");
        const index = y * previewWidth + x;
        values[index] = value;
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
    const center = Number(options.windowCenter);
    const windowWidth = Number(options.windowWidth);
    const customWindow = options.windowCenter != null && options.windowWidth != null && Number.isFinite(center) && Number.isFinite(windowWidth) && windowWidth > 0;
    const low = customWindow ? center - windowWidth / 2 : modality === "CT" ? -1000 : min;
    const high = customWindow ? center + windowWidth / 2 : modality === "CT" ? 1000 : max > min ? max : min + 1;
    for (let index = 0; index < values.length; index += 1) {
      pixels[index] = Math.round(255 * Math.max(0, Math.min(1, (values[index] - low) / (high - low))));
    }
    return { width: previewWidth, height: previewHeight, slice, sliceCount: depth, pixels: pixels.toString("base64") };
  } finally {
    fs.closeSync(header.fd);
  }
}

// Returns an already windowed/downsampled slice. raw.npy itself is never served.
router.get("/slice", (req, res) => {
  const source = resolveRawNpy(req.query);
  if (!source) return res.status(404).json({ error: "Không tìm thấy series hình ảnh" });
  try {
    res.set("Cache-Control", "no-store");
    res.json(buildSlicePreview(source, req.query.slice));
  } catch (error) {
    res.status(422).json({ error: `Không đọc được lát ảnh: ${error.message}` });
  }
});

// PNG keeps the response binary; the original volume remains on the server.
function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const name = Buffer.from(type);
  const result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length, 0); name.copy(result, 4); data.copy(result, 8);
  result.writeUInt32BE(crc32(Buffer.concat([name, data])), result.length - 4);
  return result;
}
export function encodePng(preview) {
  const pixels = Buffer.from(preview.pixels, "base64");
  const header = Buffer.alloc(13);
  header.writeUInt32BE(preview.width, 0); header.writeUInt32BE(preview.height, 4);
  header[8] = 8; // grayscale, 8-bit
  const scanlines = Buffer.alloc((preview.width + 1) * preview.height);
  for (let y = 0; y < preview.height; y++) pixels.copy(scanlines, y * (preview.width + 1) + 1, y * preview.width, (y + 1) * preview.width);
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk("IHDR", header), chunk("IDAT", deflateSync(scanlines, { level: 3 })), chunk("IEND", Buffer.alloc(0))]);
}
router.get("/png", (req, res) => {
  const source = resolveRawNpy(req.query);
  if (!source) return res.status(404).json({ error: "Không tìm thấy series hình ảnh" });
  try {
    const preview = buildSlicePreview(source, req.query.slice, req.query);
    res.set({ "Cache-Control": "no-store", "X-Slice-Index": String(preview.slice), "X-Slice-Count": String(preview.sliceCount) });
    res.type("png").send(encodePng(preview));
  } catch (error) { res.status(422).json({ error: `Không đọc được lát ảnh: ${error.message}` }); }
});

export default router;
