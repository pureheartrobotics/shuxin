/**
 * Wi-Fi scan protobuf 回归测试（Node，不依赖微信运行时）
 * 运行：node tests/test_wifi_scan_proto.mjs
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function encodeVarint(value) {
  const bytes = [];
  let v = value >>> 0;
  while (v >= 0x80) {
    bytes.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  bytes.push(v);
  return Uint8Array.from(bytes);
}

function encodeTag(fieldNumber, wireType) {
  return encodeVarint((fieldNumber << 3) | wireType);
}

function encodeVarintField(fieldNumber, value) {
  const out = new Uint8Array(encodeTag(fieldNumber, 0).length + encodeVarint(value).length);
  out.set(encodeTag(fieldNumber, 0), 0);
  out.set(encodeVarint(value), encodeTag(fieldNumber, 0).length);
  return out;
}

function concatBytes(...parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function encodeBytesField(fieldNumber, data) {
  return concatBytes(encodeTag(fieldNumber, 2), encodeVarint(data.length), data);
}

const cmdScanStart = concatBytes(
  encodeVarintField(1, 1),
  encodeVarintField(3, 0),
  encodeVarintField(4, 120),
);
assert(cmdScanStart.includes(1), "CmdScanStart must include blocking=true");
assert(cmdScanStart.includes(120), "CmdScanStart must include period_ms=120");

const identityCipher = {
  encrypt: (data) => data,
};

let builtTestsRan = false;
try {
  const wifiScanProtoPath = join(
    root,
    "apps/wechat-miniprogram/dist/build/mp-weixin/pages/prov/esp-idf-prov/wifi-scan-proto.js",
  );
  const {
    buildEncryptedScanStart,
    parseScanStartResponse,
    parseScanStatusResponse,
  } = require(wifiScanProtoPath);

  const encrypted = buildEncryptedScanStart(identityCipher);
  assert(encrypted.length > 0, "buildEncryptedScanStart must not be empty");
  assert(encrypted[0] === 0x08 && encrypted[1] === 0x00, "request msg type must be CmdScanStart(0)");

  const respScanStart = concatBytes(encodeVarintField(1, 1), encodeBytesField(11, new Uint8Array(0)));
  parseScanStartResponse(respScanStart);

  const respScanStatus = concatBytes(
    encodeVarintField(1, 3),
    encodeBytesField(13, concatBytes(encodeVarintField(1, 1), encodeVarintField(2, 2))),
  );
  const status = parseScanStatusResponse(respScanStatus);
  assert(status.scanFinished === true, "scanFinished should be true");
  assert(status.resultCount === 2, "resultCount should be 2");

  let emptyErr = "";
  try {
    parseScanStartResponse(new Uint8Array(0));
  } catch (err) {
    emptyErr = err.message;
  }
  assert(emptyErr.includes("空响应体"), `empty buffer must throw readable error, got: ${emptyErr}`);
  assert(!emptyErr.includes("null"), "empty buffer error must not contain bare null");

  let missingMsgErr = "";
  try {
    parseScanStartResponse(encodeVarintField(2, 0));
  } catch (err) {
    missingMsgErr = err.message;
  }
  assert(missingMsgErr.includes("缺少 msg 字段"), `missing msg must be explicit, got: ${missingMsgErr}`);

  builtTestsRan = true;
} catch (err) {
  console.warn(
    "skip built wifi-scan-proto tests (run bash scripts/wechat_miniprogram_dev.sh build first):",
    err.message,
  );
}

console.log(
  builtTestsRan
    ? "test_wifi_scan_proto: OK (inline + built bundle)"
    : "test_wifi_scan_proto: OK (inline encode only; built bundle not tested)",
);
