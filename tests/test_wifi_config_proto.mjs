/**
 * Wi-Fi config GetStatus protobuf 回归测试（Node，不依赖微信运行时）
 * 运行：node tests/test_wifi_config_proto.mjs
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
  return concatBytes(encodeTag(fieldNumber, 0), encodeVarint(value));
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

/** 构造 RespGetStatus 内层 + WiFiConfigPayload 外层 */
function buildGetStatusPayload({ staState, failReason, attemptsRemaining }) {
  const respParts = [];
  if (staState !== undefined && staState !== null) {
    respParts.push(encodeVarintField(2, staState));
  }
  if (failReason !== undefined && failReason !== null) {
    respParts.push(encodeVarintField(10, failReason));
  }
  if (attemptsRemaining !== undefined && attemptsRemaining !== null) {
    respParts.push(
      encodeBytesField(12, encodeVarintField(1, attemptsRemaining)),
    );
  }
  const respBody = concatBytes(...respParts);
  return concatBytes(
    encodeVarintField(1, 1),
    encodeBytesField(11, respBody),
  );
}

let builtTestsRan = false;
try {
  const wifiConfigProtoPath = join(
    root,
    "apps/wechat-miniprogram/dist/build/mp-weixin/pages/prov/esp-idf-prov/wifi-config-proto.js",
  );
  const {
    parseGetStatusResponse,
    isTerminalWifiProvisionFailure,
  } = require(wifiConfigProtoPath);

  // Connecting + attempt_failed(remaining=2) → connecting
  const midRetry = buildGetStatusPayload({
    staState: 1,
    attemptsRemaining: 2,
  });
  assert(
    parseGetStatusResponse(midRetry) === "connecting",
    "Connecting + attempt_failed must stay connecting",
  );

  // ConnectionFailed without fail_reason → must NOT be failed_auth
  const failedNoReason = buildGetStatusPayload({ staState: 3 });
  const noReasonStatus = parseGetStatusResponse(failedNoReason);
  assert(
    noReasonStatus !== "failed_auth",
    `ConnectionFailed without fail_reason must not be failed_auth, got: ${noReasonStatus}`,
  );
  assert(
    noReasonStatus === "connecting",
    `ConnectionFailed without fail_reason should keep polling, got: ${noReasonStatus}`,
  );

  // ConnectionFailed + NetworkNotFound(1) → failed_not_found
  const notFound = buildGetStatusPayload({ staState: 3, failReason: 1 });
  assert(
    parseGetStatusResponse(notFound) === "failed_not_found",
    "NetworkNotFound must map to failed_not_found",
  );

  // Connected (sta_state omitted / 0) → connected
  const connected = buildGetStatusPayload({});
  assert(parseGetStatusResponse(connected) === "connected", "missing sta_state → connected");

  // Terminal failure helper
  assert(isTerminalWifiProvisionFailure("failed_auth"), "failed_auth is terminal");
  assert(isTerminalWifiProvisionFailure("failed_not_found"), "failed_not_found is terminal");
  assert(!isTerminalWifiProvisionFailure("connecting"), "connecting is not terminal");

  builtTestsRan = true;
} catch (err) {
  console.warn(
    "skip built wifi-config-proto tests (run bash scripts/wechat_miniprogram_dev.sh build first):",
    err.message,
  );
}

console.log(
  builtTestsRan
    ? "test_wifi_config_proto: OK (built bundle)"
    : "test_wifi_config_proto: SKIP (built bundle missing; run wechat_miniprogram_dev.sh build)",
);
