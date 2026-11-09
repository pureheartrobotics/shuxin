import {
  concatBytes,
  decodeFields,
  encodeBytesField,
  encodeVarintField,
  getBytesField,
  getVarintField,
  utf8Decode,
} from "./protobuf-wire";
import { bytesToHex } from "./wifi-scan-debug";

const TYPE_CMD_SCAN_START = 0;
const TYPE_RESP_SCAN_START = 1;
const TYPE_CMD_SCAN_STATUS = 2;
const TYPE_RESP_SCAN_STATUS = 3;
const TYPE_CMD_SCAN_RESULT = 4;
const TYPE_RESP_SCAN_RESULT = 5;

export type WifiScanEntry = {
  ssid: string;
  rssi: number;
  channel: number;
};

function toSignedInt32(value: number): number {
  return value | 0;
}

function scanParseError(label: string, decrypted: Uint8Array, msgType: number | null, expectedType?: number): Error {
  const hex = bytesToHex(decrypted);
  if (msgType === null || msgType === undefined) {
    return new Error(`无法解析 ${label}（缺少 msg 字段，decrypted=${hex}）`);
  }
  if (expectedType !== undefined && msgType !== expectedType) {
    return new Error(`${label} 响应类型错误: 期望 ${expectedType}，实际 ${msgType}，decrypted=${hex}`);
  }
  return new Error(`无法解析 ${label}（decrypted=${hex}）`);
}

function parseWifiScanEntry(buffer: Uint8Array): WifiScanEntry | null {
  const fields = decodeFields(buffer);
  const ssidBytes = getBytesField(fields, 1);
  if (!ssidBytes || ssidBytes.length === 0) {
    return null;
  }
  const ssid = utf8Decode(ssidBytes).replace(/\0/g, "").trim();
  if (!ssid) {
    return null;
  }
  const channel = getVarintField(fields, 2) ?? 0;
  const rssi = toSignedInt32(getVarintField(fields, 3) ?? 0);
  return { ssid, rssi, channel };
}

function assertScanResponseType(decrypted: Uint8Array, expectedType: number, label: string): void {
  if (!decrypted || decrypted.length === 0) {
    throw new Error(`${label} 收到空响应体`);
  }
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== expectedType) {
    throw scanParseError(label, decrypted, msgType, expectedType);
  }
  const status = getVarintField(fields, 2) ?? 0;
  if (status !== 0) {
    throw new Error(`${label} 失败（status=${status}，decrypted=${bytesToHex(decrypted)}）`);
  }
}

export function buildEncryptedScanStart(cipher: { encrypt: (data: Uint8Array) => Uint8Array }): Uint8Array {
  const cmdScanStart = concatBytes(
    encodeVarintField(1, 1),
    encodeVarintField(3, 0),
    encodeVarintField(4, 120),
  );
  const inner = concatBytes(encodeVarintField(1, TYPE_CMD_SCAN_START), encodeBytesField(10, cmdScanStart));
  return cipher.encrypt(inner);
}

export function buildEncryptedScanStatus(cipher: { encrypt: (data: Uint8Array) => Uint8Array }): Uint8Array {
  const inner = concatBytes(
    encodeVarintField(1, TYPE_CMD_SCAN_STATUS),
    encodeBytesField(12, new Uint8Array(0)),
  );
  return cipher.encrypt(inner);
}

export function buildEncryptedScanResult(
  cipher: { encrypt: (data: Uint8Array) => Uint8Array },
  startIndex: number,
  count: number,
): Uint8Array {
  const cmdScanResult = concatBytes(encodeVarintField(1, startIndex), encodeVarintField(2, count));
  const inner = concatBytes(encodeVarintField(1, TYPE_CMD_SCAN_RESULT), encodeBytesField(14, cmdScanResult));
  return cipher.encrypt(inner);
}

export function parseScanStartResponse(decrypted: Uint8Array): void {
  assertScanResponseType(decrypted, TYPE_RESP_SCAN_START, "ScanStart");
}

export function parseScanStatusResponse(decrypted: Uint8Array): { scanFinished: boolean; resultCount: number } {
  if (!decrypted || decrypted.length === 0) {
    throw new Error("ScanStatus 收到空响应体");
  }
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== TYPE_RESP_SCAN_STATUS) {
    throw scanParseError("ScanStatus", decrypted, msgType, TYPE_RESP_SCAN_STATUS);
  }
  const status = getVarintField(fields, 2) ?? 0;
  if (status !== 0) {
    throw new Error(`Wi-Fi 扫描状态查询失败（status=${status}，decrypted=${bytesToHex(decrypted)}）`);
  }
  const resp = getBytesField(fields, 13);
  if (!resp) {
    return { scanFinished: false, resultCount: 0 };
  }
  const respFields = decodeFields(resp);
  return {
    scanFinished: (getVarintField(respFields, 1) ?? 0) === 1,
    resultCount: getVarintField(respFields, 2) ?? 0,
  };
}

export function parseScanResultResponse(decrypted: Uint8Array): WifiScanEntry[] {
  if (!decrypted || decrypted.length === 0) {
    throw new Error("ScanResult 收到空响应体");
  }
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== TYPE_RESP_SCAN_RESULT) {
    throw scanParseError("ScanResult", decrypted, msgType, TYPE_RESP_SCAN_RESULT);
  }
  const status = getVarintField(fields, 2) ?? 0;
  if (status !== 0) {
    throw new Error(`获取 Wi-Fi 扫描结果失败（status=${status}，decrypted=${bytesToHex(decrypted)}）`);
  }
  const resp = getBytesField(fields, 15);
  if (!resp) {
    return [];
  }
  const respFields = decodeFields(resp);
  const entries: WifiScanEntry[] = [];
  for (const field of respFields) {
    if (field.number === 1 && field.wireType === 2 && field.value instanceof Uint8Array) {
      const entry = parseWifiScanEntry(field.value);
      if (entry) {
        entries.push(entry);
      }
    }
  }
  return entries;
}

/** 供单测校验 CmdScanStart 明文编码 */
export function buildScanStartInnerPlain(): Uint8Array {
  const cmdScanStart = concatBytes(
    encodeVarintField(1, 1),
    encodeVarintField(3, 0),
    encodeVarintField(4, 120),
  );
  return concatBytes(encodeVarintField(1, TYPE_CMD_SCAN_START), encodeBytesField(10, cmdScanStart));
}
