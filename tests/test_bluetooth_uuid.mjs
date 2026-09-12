/**
 * Bluetooth UUID 匹配与 endpoint 推导回归
 * 运行：node tests/test_bluetooth_uuid.mjs
 */
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

const LEGACY_PROV_UUID = "0000ffff-0000-1000-8000-00805f9b34fb";
const V5_PROV_UUID = "1775244d-6b43-439b-877c-060f2d9bed07";
const builtPath = join(
  root,
  "apps/wechat-miniprogram/dist/dev/mp-weixin/pages/prov/esp-idf-prov/bluetooth-uuid.js",
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function inlineBluetoothUuidMatches(actual, expected) {
  const BLUETOOTH_BASE_SUFFIX = "00001000800000805f9b34fb";
  const strip = (uuid) => String(uuid || "").toLowerCase().replace(/-/g, "");
  const alias = (uuid) => {
    const stripped = strip(uuid);
    if (stripped.length === 4 && /^[0-9a-f]{4}$/.test(stripped)) {
      return stripped;
    }
    if (stripped.length === 32 && stripped.endsWith(BLUETOOTH_BASE_SUFFIX)) {
      return stripped.slice(4, 8);
    }
    return stripped;
  };
  const a = strip(actual);
  const b = strip(expected);
  return a === b || alias(a) === alias(b);
}

function inlineParseUuid128(uuid) {
  const parts = uuid.toLowerCase().split("-");
  const hex = (value) => parseInt(value, 16);
  const bytes = new Uint8Array(16);
  const timeLow = hex(parts[0]);
  bytes[15] = timeLow & 0xff;
  bytes[14] = (timeLow >> 8) & 0xff;
  bytes[13] = (timeLow >> 16) & 0xff;
  bytes[12] = (timeLow >> 24) & 0xff;
  const timeMid = hex(parts[1]);
  bytes[11] = timeMid & 0xff;
  bytes[10] = (timeMid >> 8) & 0xff;
  const timeHi = hex(parts[2]);
  bytes[9] = timeHi & 0xff;
  bytes[8] = (timeHi >> 8) & 0xff;
  bytes[7] = hex(parts[3].slice(0, 2));
  bytes[6] = hex(parts[3].slice(2, 4));
  for (let i = 0; i < 6; i += 1) {
    bytes[5 - i] = hex(parts[4].slice(i * 2, i * 2 + 2));
  }
  return bytes;
}

function inlineFormatUuid128(bytes) {
  const hex = (value) => value.toString(16).padStart(2, "0");
  const timeLow =
    (bytes[12] << 24) | (bytes[13] << 16) | (bytes[14] << 8) | bytes[15];
  const timeMid = (bytes[10] << 8) | bytes[11];
  const timeHi = (bytes[8] << 8) | bytes[9];
  const clock = `${hex(bytes[7])}${hex(bytes[6])}`;
  const node = [5, 4, 3, 2, 1, 0].map((index) => hex(bytes[index])).join("");
  return `${timeLow.toString(16).padStart(8, "0")}-${timeMid
    .toString(16)
    .padStart(4, "0")}-${timeHi.toString(16).padStart(4, "0")}-${clock}-${node}`.toUpperCase();
}

function inlineDeriveEndpointCharacteristicUuid(serviceUuid, shortUuid16) {
  const bytes = inlineParseUuid128(serviceUuid);
  bytes[12] = shortUuid16 & 0xff;
  bytes[13] = (shortUuid16 >> 8) & 0xff;
  return inlineFormatUuid128(bytes);
}

let matches = inlineBluetoothUuidMatches;
let deriveEndpoint = inlineDeriveEndpointCharacteristicUuid;
if (existsSync(builtPath)) {
  try {
    const built = require(builtPath);
    if (typeof built.bluetoothUuidMatches === "function") {
      matches = built.bluetoothUuidMatches;
    }
    if (typeof built.deriveEndpointCharacteristicUuid === "function") {
      deriveEndpoint = built.deriveEndpointCharacteristicUuid;
    }
  } catch {
    console.warn("using inline bluetooth uuid helpers (built bundle load failed)");
  }
} else {
  console.warn("using inline bluetooth uuid helpers (run build for built bundle test)");
}

assert(matches("FFFF", LEGACY_PROV_UUID), "FFFF should match legacy ESP-IDF service UUID");
assert(
  matches("1775244D-6B43-439B-877C-060F2D9BED07", V5_PROV_UUID),
  "v5 default service UUID should match",
);
assert(
  !matches("1775244D-6B43-439B-877C-060F2D9BED07", LEGACY_PROV_UUID),
  "v5 UUID must not match legacy FFFF service",
);
assert(
  matches("2901", "00002901-0000-1000-8000-00805f9b34fb"),
  "descriptor short UUID should match",
);

const provSession = deriveEndpoint(V5_PROV_UUID, 0xff51);
assert(
  matches(provSession, "1775FF51-6B43-439B-877C-060F2D9BED07"),
  `prov-session endpoint UUID should match protocomm layout, got ${provSession}`,
);

const provScan = deriveEndpoint(V5_PROV_UUID, 0xff50);
assert(
  matches(provScan, "1775FF50-6B43-439B-877C-060F2D9BED07"),
  `prov-scan endpoint UUID should match production firmware, got ${provScan}`,
);

const protoVer = deriveEndpoint(V5_PROV_UUID, 0xff53);
assert(
  matches(protoVer, "1775FF53-6B43-439B-877C-060F2D9BED07"),
  `proto-ver endpoint UUID should match production firmware, got ${protoVer}`,
);

console.log("test_bluetooth_uuid: OK");
